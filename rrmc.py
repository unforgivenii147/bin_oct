#!/data/data/com.termux/files/home/.local/bin/python
"""
Strip comments and docstrings from Python source files using libcst.
Walks the given target paths (defaults to CWD), skips common cache directories,
and rewrites each file that lost comments or docstrings. Inserts `pass` when a
function/class body would otherwise become empty. Uses a fixed
multiprocessing.Pool of 8 workers; logging via loguru.
"""

import argparse
import ast
from collections.abc import Sequence
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import libcst as cst
from loguru import logger

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {".git", "__pycache__", ".ruff_cache", ".pytest_cache"}
)
MAX_WORKERS: Final[int] = 8

Task = tuple[Path, Path]


def _is_docstring_statement(stmt: cst.BaseStatement) -> bool:
    """
    Return whether ``stmt`` is a module/function/class docstring.

    A docstring is a single-expression statement whose only element is a
    non-bytes string literal.

    Args:
        stmt: A statement from a module or ``IndentedBlock`` body.

    Returns:
        ``True`` if ``stmt`` is a docstring, ``False`` otherwise.
    """
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    expr = stmt.body[0]
    if not isinstance(expr, cst.Expr):
        return False
    value = expr.value
    if not isinstance(value, cst.SimpleString):
        return False
    return "b" not in value.prefix.lower()


def _is_docstring_small_statement(stmt: cst.BaseSmallStatement) -> bool:
    """
    Return whether ``stmt`` is a docstring inside a one-line suite.

    Args:
        stmt: A small statement from a ``SimpleStatementSuite`` body.

    Returns:
        ``True`` if ``stmt`` is a docstring, ``False`` otherwise.
    """
    if not isinstance(stmt, cst.Expr):
        return False
    value = stmt.value
    if not isinstance(value, cst.SimpleString):
        return False
    return "b" not in value.prefix.lower()


class PythonCleaner(cst.CSTTransformer):
    """
    libcst transformer that removes all comments and every docstring on
    modules, functions (including ``async``), and classes.

    Attributes:
        comments_removed: Number of ``Comment`` nodes removed.
        docstrings_removed: Number of docstrings removed.
    """

    def __init__(self) -> None:
        """Initialize the transformer with zero counters."""
        super().__init__()
        self.comments_removed: int = 0
        self.docstrings_removed: int = 0

    def leave_Comment(
        self,
        original_node: cst.Comment,
        updated_node: cst.Comment,
    ) -> cst.Comment | cst.RemovalSentinel:
        """
        Remove every comment encountered and increment the counter.

        Args:
            original_node: The original ``Comment`` node.
            updated_node: The (unchanged) ``Comment`` node.

        Returns:
            ``RemovalSentinel.REMOVE``.
        """
        self.comments_removed += 1
        return cst.RemovalSentinel.REMOVE

    def _strip_statements(
        self, body: Sequence[cst.BaseStatement]
    ) -> tuple[cst.BaseStatement, ...]:
        """
        Drop the leading docstring from a statement sequence, if present.

        Args:
            body: A module or ``IndentedBlock`` body.

        Returns:
            The body with the leading docstring removed, or unchanged.
        """
        if not body:
            return tuple(body)
        if _is_docstring_statement(body[0]):
            self.docstrings_removed += 1
            return tuple(body[1:])
        return tuple(body)

    def _strip_suite(self, suite: cst.BaseSuite) -> cst.BaseSuite:
        """
        Drop the leading docstring from a function/class suite; insert
        ``pass`` if the suite would otherwise become empty.

        Args:
            suite: An ``IndentedBlock`` or ``SimpleStatementSuite``.

        Returns:
            The transformed suite.
        """
        if isinstance(suite, cst.IndentedBlock):
            new_body: tuple[cst.BaseStatement, ...] = self._strip_statements(suite.body)
            if not new_body:
                new_body = (cst.SimpleStatementLine(body=[cst.Pass()]),)
            return suite.with_changes(body=new_body)

        if isinstance(suite, cst.SimpleStatementSuite):
            small_body: tuple[cst.BaseSmallStatement, ...] = tuple(suite.body)
            if small_body and _is_docstring_small_statement(small_body[0]):
                self.docstrings_removed += 1
                small_body = small_body[1:]
            if not small_body:
                small_body = (cst.Pass(),)
            return suite.with_changes(body=small_body)

        return suite

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        """Strip the module-level docstring, if present."""
        new_body: tuple[cst.BaseStatement, ...] = self._strip_statements(
            updated_node.body
        )
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Strip the function's docstring (covers ``async def`` too)."""
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        """Strip the class's docstring."""
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))


def is_python_script(path: Path) -> bool:
    """
    Return whether ``path`` looks like a Python source file.

    Matches ``*.py`` files, or extensionless files whose first line is a
    Python shebang.

    Args:
        path: Candidate file path.

    Returns:
        ``True`` if the file should be cleaned, ``False`` otherwise.
    """
    if path.suffix == ".py":
        return True
    try:
        with path.open("r", encoding="utf-8") as f:
            first_line: str = f.readline()
        return first_line.startswith("#!") and "python" in first_line.lower()
    except Exception:
        return False


def process_file(task: Task) -> int:
    """
    Strip comments and docstrings from a single Python file.

    Args:
        task: ``(file_path, root)`` tuple; ``root`` is used for relative
            logging.

    Returns:
        Total number of comments and docstrings removed (0 on error or no-op).
    """
    path, root = task
    try:
        rel_path: Path = path.relative_to(root)
        source: str = path.read_text(encoding="utf-8")

        module: cst.Module = cst.parse_module(source)
        cleaner: PythonCleaner = PythonCleaner()
        modified_module: cst.Module = module.visit(cleaner)
        cleaned_code: str = modified_module.code

        if cleaner.comments_removed == 0 and cleaner.docstrings_removed == 0:
            return 0

        # Validate the cleaned code still parses.
        ast.parse(cleaned_code)

        path.write_text(cleaned_code, encoding="utf-8")
        print(
            f"{rel_path}: removed {cleaner.comments_removed} comments, "
            f"{cleaner.docstrings_removed} docstrings"
        )
        return cleaner.comments_removed + cleaner.docstrings_removed
    except Exception as exc:
        logger.error(f"Failed {path}: {exc}")
        return 0


def main() -> None:
    """
    Parse CLI arguments, discover target files, and run cleaning in parallel.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Strip comments and docstrings from Python files using libcst."
    )
    parser.add_argument("targets", nargs="*", type=str)
    args: argparse.Namespace = parser.parse_args()

    root: Path = Path.cwd().resolve()
    targets: list[Path] = (
        [Path(t).resolve() for t in args.targets] if args.targets else [root]
    )

    files_to_process: list[Task] = []
    for target in targets:
        if target.is_file():
            if not any(part in SKIP_DIRS for part in target.parts) and is_python_script(
                target
            ):
                files_to_process.append((target, root))
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
                    if is_python_script(path):
                        files_to_process.append((path.resolve(), root))

    if not files_to_process:
        print("No Python files found to process.")
        return

    total_removed: int = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[int]] = [
            pool.apply_async(process_file, (task,)) for task in files_to_process
        ]
        for async_res in async_results:
            try:
                total_removed += async_res.get()
            except Exception as exc:
                logger.error(f"Worker raised: {exc}")

    logger.success(f"Cleanup complete. Total elements removed: {total_removed}")


if __name__ == "__main__":
    raise SystemExit(main())
