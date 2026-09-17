#!/data/data/com.termux/files/home/.local/bin/python
"""
Strip comments and docstrings from every Python file under a target directory
using libcst, replacing an earlier regex-based approach. For each file, a
``.bak`` backup is created first, then a ``StripTransformer`` removes all
comments and module/function/class docstrings (inserting ``pass`` if a body
would become empty), and the result is validated with :func:`ast.parse` before
being written back. Files are processed with a fixed multiprocessing.Pool of 8
workers; logging via loguru.
"""

import ast
import shutil
from collections.abc import Sequence
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import libcst as cst
from dh import get_pyfiles  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8


class StripTransformer(cst.CSTTransformer):
    """
    libcst transformer that removes all comments and docstrings.

    Comments are removed unconditionally. Module-, function-, and class-level
    docstrings (bare string expression statements) are removed; if that would
    leave a function or class body empty, a ``pass`` statement is inserted.
    """

    def leave_Comment(
        self, original_node: cst.Comment, updated_node: cst.Comment
    ) -> cst.BaseLeaf | cst.RemovalSentinel:
        """
        Remove every comment node.

        Args:
            original_node: The original ``Comment`` node.
            updated_node: The (possibly-updated) ``Comment`` node.

        Returns:
            Always ``RemovalSentinel.REMOVE``.
        """
        return cst.RemovalSentinel.REMOVE

    @staticmethod
    def _strip_leading_docstring(
        body: Sequence[cst.BaseStatement],
    ) -> tuple[cst.BaseStatement, ...]:
        """
        Drop the first statement if it is a bare string expression (a docstring).

        Args:
            body: The suite's statement sequence.

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
        Remove a leading docstring from a function/class suite, inserting
        ``pass`` if the suite would otherwise be empty.

        Args:
            suite: An ``IndentedBlock`` or ``SimpleStatementSuite``.

        Returns:
            The transformed suite.
        """
        if isinstance(suite, cst.IndentedBlock):
            new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_docstring(
                suite.body
            )
            if not new_body:
                new_body = (cst.SimpleStatementLine(body=[cst.Pass()]),)
            return suite.with_changes(body=new_body)

        if isinstance(suite, cst.SimpleStatementSuite):
            new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_docstring(
                suite.body
            )
            if not new_body:
                new_body = (cst.Pass(),)
            return suite.with_changes(body=new_body)

        return suite

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        """Strip the module-level docstring, if present."""
        new_body: tuple[cst.BaseStatement, ...] = self._strip_leading_docstring(
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


def strip_comments_and_docstrings(file_path_str: str) -> bool:
    """
    Strip all comments and docstrings from a single Python source file.

    A ``.bak`` copy of the file is created before modification. The cleaned
    output is validated with :func:`ast.parse`; if validation fails, the
    original file is left untouched.

    Args:
        file_path_str: Path (as a string) to the Python source file.

    Returns:
        ``True`` if the file was rewritten successfully, ``False`` otherwise.
    """
    file_path: Path = Path(file_path_str)
    backup_path: Path = file_path.with_suffix(file_path.suffix + ".bak")

    try:
        original_content: str = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Error reading file {file_path}: {exc}")
        return False

    # Ensure the input parses cleanly before doing anything destructive.
    try:
        ast.parse(original_content, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning(
            f"Original code has syntax error: {file_path} - {exc}. Skipping."
        )
        return False

    try:
        module: cst.Module = cst.parse_module(original_content)
    except cst.ParserSyntaxError as exc:
        logger.warning(f"libcst failed to parse {file_path}: {exc}. Skipping.")
        return False

    transformer: StripTransformer = StripTransformer()
    new_module: cst.Module = module.visit(transformer)
    final_code: str = new_module.code

    if final_code == original_content:
        print(f"No comments or docstrings to strip in {file_path}")
        return False

    try:
        ast.parse(final_code, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning(
            f"Syntax error after stripping comments/docstrings from {file_path}. "
            f"Reverting. ({exc})"
        )
        return False

    try:
        shutil.copy2(file_path, backup_path)
        print(f"Backup created: {backup_path}")
    except Exception as exc:
        logger.error(f"Error creating backup for {file_path}: {exc}")
        return False

    try:
        file_path.write_text(final_code, encoding="utf-8")
        print(f"Successfully stripped comments/docstrings from {file_path}")
        return True
    except Exception as exc:
        logger.error(f"Error writing cleaned file {file_path}: {exc}")
        try:
            shutil.move(str(backup_path), str(file_path))
            print(f"Restored original content from backup for {file_path}")
        except Exception as restore_exc:
            logger.critical(
                f"Failed to write cleaned file and restore backup for {file_path}: "
                f"{restore_exc}"
            )
        return False


def process_directory(directory: str) -> None:
    """
    Strip comments and docstrings from every Python file under ``directory``.

    Args:
        directory: Root directory to scan for ``.py`` files.
    """
    python_files: list[Path] = list(get_pyfiles(directory))
    print(f"Found {len(python_files)} Python files to process.")

    if not python_files:
        print("Nothing to do.")
        return

    processed_count: int = 0
    ordered: list[Path] = sorted(python_files)

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[bool]] = [
            pool.apply_async(strip_comments_and_docstrings, (str(file_path),))
            for file_path in ordered
        ]
        for file_path, async_res in zip(ordered, async_results):
            try:
                if async_res.get():
                    processed_count += 1
            except Exception as exc:
                logger.error(f"Error processing future for {file_path}: {exc}")

    print(
        f"Finished processing. Successfully stripped comments/docstrings from "
        f"{processed_count}/{len(python_files)} files."
    )


def main() -> None:
    """Entry point: run stripping against the current directory."""
    target_directory: str = "."
    print(
        f"Starting comment and docstring stripping in directory: "
        f"{Path(target_directory).resolve()}"
    )
    process_directory(target_directory)


if __name__ == "__main__":
    raise SystemExit(main())
