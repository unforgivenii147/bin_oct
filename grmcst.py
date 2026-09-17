#!/data/data/com.termux/files/home/.local/bin/python
"""
Strip comments and docstrings from Python source files using libcst.
Preserves shebang lines, `# type:` directives, and `# fmt:` pragmas while
removing all other comments and module/function/class docstrings. Discovers
targets from CLI path arguments (defaults to CWD), processes them in a fixed
multiprocessing.Pool of 8 workers, validates the result with ast.parse, and
reports per-file status via loguru.
"""

import argparse
import ast
import sys
from collections.abc import Sequence
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import libcst as cst

MAX_WORKERS: Final[int] = 8
PRESERVE_PREFIXES: Final[tuple[str, ...]] = ("#!", "# type:", "# fmt:")
PRESERVE_EXACT: Final[frozenset[str]] = frozenset(
    {"# fmt: skip", "# fmt: on", "# fmt: off"}
)


def should_preserve_comment(comment_text: str) -> bool:
    """
    Decide whether a comment must be preserved during stripping.

    Preserves shebang lines, PEP 484 type directives, and Black/isort fmt
    pragmas.

    Args:
        comment_text: The raw comment text, including the leading ``#``.

    Returns:
        ``True`` if the comment should be kept, ``False`` otherwise.
    """
    stripped: str = comment_text.strip()
    return stripped.startswith(PRESERVE_PREFIXES) or stripped in PRESERVE_EXACT


class StripTransformer(cst.CSTTransformer):
    """
    libcst transformer that removes non-preserved comments and docstrings.

    Docstrings are removed from :class:`cst.Module`,
    :class:`cst.FunctionDef` (including ``async def``), and
    :class:`cst.ClassDef`. If removing a body docstring would leave the body
    empty, a ``pass`` statement is inserted.
    """

    def leave_Comment(
        self, original_node: cst.Comment, updated_node: cst.Comment
    ) -> cst.BaseLeaf | cst.RemovalSentinel:
        """
        Remove the comment unless it matches a preservation rule.

        Args:
            original_node: The original ``Comment`` node.
            updated_node: The (possibly-changed) ``Comment`` node.

        Returns:
            The unchanged ``Comment`` to keep it, or ``RemovalSentinel.REMOVE``.
        """
        if should_preserve_comment(updated_node.value):
            return updated_node
        return cst.RemovalSentinel.REMOVE

    @staticmethod
    def _strip_leading_string(
        body: Sequence[cst.BaseStatement],
    ) -> tuple[cst.BaseStatement, ...]:
        """
        Drop the first statement if it is a bare string expression (a docstring).

        Args:
            body: The sequence of statements to inspect.

        Returns:
            The body with the leading docstring removed, or unchanged if the
            first statement is not a docstring.
        """
        if not body:
            return tuple(body)

        first: cst.BaseStatement = body[0]
        if (
            isinstance(first, cst.SimpleStatementLine)
            and len(first.body) == 1
            and isinstance(first.body[0], cst.Expr)
            and isinstance(first.body[0].value, cst.SimpleString)
        ):
            return tuple(body[1:])

        return tuple(body)

    def _strip_suite(self, suite: cst.BaseSuite) -> cst.BaseSuite:
        """
        Strip a leading docstring from a function/class suite, inserting
        ``pass`` if the suite would otherwise be empty.

        Args:
            suite: An ``IndentedBlock`` or ``SimpleStatementSuite``.

        Returns:
            The transformed suite.
        """
        if isinstance(suite, cst.IndentedBlock):
            new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_string(
                suite.body
            )
            if not new_body:
                new_body = (cst.SimpleStatementLine(body=[cst.Pass()]),)
            return suite.with_changes(body=new_body)

        if isinstance(suite, cst.SimpleStatementSuite):
            new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_string(
                suite.body
            )
            if not new_body:
                new_body = (cst.Pass(),)
            return suite.with_changes(body=new_body)

        return suite

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        """Strip the module-level docstring, if any."""
        new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_string(
            updated_node.body
        )
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Strip the docstring from a function (including ``async def``)."""
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        """Strip the docstring from a class body."""
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))


def process_file(file_path: Path) -> str:
    """
    Strip comments and docstrings from a single Python file in place.

    Parses the file with libcst, applies :class:`StripTransformer`, validates
    the regenerated code with :func:`ast.parse`, and writes the result back.

    Args:
        file_path: Path to the Python source file to process.

    Returns:
        A human-readable status message prefixed with ``[SUCCESS]``,
        ``[SKIPPED]``, ``[WARNING]``, or ``[ERROR]``.
    """
    try:
        source: str = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"[ERROR] Failed to read {file_path}: {exc}"

    try:
        module: cst.Module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return f"[ERROR] Failed to parse {file_path}: {exc}"

    try:
        transformer: StripTransformer = StripTransformer()
        new_module: cst.Module = module.visit(transformer)
    except Exception as exc:
        return f"[ERROR] Transformation failed for {file_path}: {exc}"

    final_code: str = new_module.code
    if final_code == source:
        return f"[SKIPPED] No structural modifications needed for {file_path}"

    try:
        ast.parse(final_code, filename=str(file_path))
    except SyntaxError as exc:
        return f"[WARNING] Validation failed for {file_path} (Changes rejected): {exc}"

    try:
        file_path.write_text(final_code, encoding="utf-8")
        return f"[SUCCESS] Processed and stripped: {file_path}"
    except Exception as exc:
        return f"[ERROR] Failed to save updates to {file_path}: {exc}"


def gather_files(inputs: list[str]) -> list[Path]:
    """
    Resolve the list of ``.py`` files to process.

    Args:
        inputs: Raw CLI path arguments. If empty, the current working
            directory is searched recursively.

    Returns:
        A sorted, de-duplicated list of ``.py`` file paths.
    """
    files: set[Path] = set()

    if not inputs:
        files.update(Path(".").rglob("*.py"))
        return sorted(files)

    for item in inputs:
        p: Path = Path(item)
        if p.is_file() and p.suffix == ".py":
            files.add(p)
        elif p.is_dir():
            files.update(p.rglob("*.py"))

    return sorted(files)


def main() -> None:
    """Parse CLI arguments and process each target file in parallel."""
    parser = argparse.ArgumentParser(
        description="Strip comments and docstrings using libcst safely."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Target files or directories to process. Defaults to '.' if empty.",
    )
    args: argparse.Namespace = parser.parse_args()

    targets: list[Path] = gather_files(args.paths)
    if not targets:
        print("No target Python source files detected.")
        sys.exit(0)

    print(
        f"Queue loaded. Processing {len(targets)} target files via Parallel Pipeline..."
    )

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[str]] = [
            pool.apply_async(process_file, (target,)) for target in targets
        ]
        for async_res in async_results:
            result_string: str = async_res.get()
            print(result_string)


if __name__ == "__main__":
    raise SystemExit(main())
