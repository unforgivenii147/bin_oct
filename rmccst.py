#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python script that strips comments and non-module docstrings from Python files.

The script should:
- Accept file and/or directory paths as positional arguments (default to '.').
- Recursively discover all .py files under directories.
- Parse each file with libcst, removing all comments and every docstring except the module docstring.
- Preserve shebang lines.
- Validate transformed code with ast.parse; skip writing and report errors when invalid.
- Process files using multiprocessing.Pool.apply_async with a fixed pool of 8 workers.
- Use loguru for logging and pathlib for all path handling.
- Include complete type hints, a module docstring, and docstrings for all functions and classes.
"""

from __future__ import annotations

import argparse
import ast
import io
import multiprocessing
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import libcst as cst
import libcst.matchers as m
from loguru import logger

POOL_SIZE: Final[int] = 8


def find_module_docstring(source: str) -> tuple[int, int] | None:
    """Return the (start_line, end_line) of the module docstring, or None if absent.

    Args:
        source: The Python source code to inspect.

    Returns:
        A tuple of start and end line numbers for the module docstring,
        or None when no module docstring exists or the source is invalid.
    """
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    doc = ast.get_docstring(module)
    if doc is None:
        return None
    if not module.body:
        return None
    first_stmt = module.body[0]
    if not isinstance(first_stmt, ast.Expr) or not isinstance(
        getattr(first_stmt, "value", None), ast.Constant
    ):
        return None
    value = first_stmt.value
    if not isinstance(value.value, str):
        return None
    start_line = getattr(value, "lineno", None)
    end_line = getattr(value, "end_lineno", None)
    if start_line is None or end_line is None:
        return None
    return start_line, end_line


class StripCommentsAndDocstrings(cst.CSTTransformer):
    """CST transformer that removes comments and all non-module docstrings."""

    module_doc_range: tuple[int, int] | None
    comments_removed: int
    docstrings_removed: int

    def __init__(self, module_doc_range: tuple[int, int] | None) -> None:
        """Initialize the transformer.

        Args:
            module_doc_range: Line range of the module docstring, if any.
        """
        super().__init__()
        self.module_doc_range = module_doc_range
        self.comments_removed = 0
        self.docstrings_removed = 0

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        """Remove trailing comments.

        Args:
            original_node: The original node.
            updated_node: The updated node.

        Returns:
            The updated node with any comment removed.
        """
        if updated_node.comment is not None:
            self.comments_removed += 1
            updated_node = updated_node.with_changes(comment=None)
        return updated_node

    def leave_EmptyLine(
        self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine
    ) -> cst.EmptyLine:
        """Remove comments on empty lines.

        Args:
            original_node: The original node.
            updated_node: The updated node.

        Returns:
            The updated node with any comment removed.
        """
        if updated_node.comment is not None:
            self.comments_removed += 1
            updated_node = updated_node.with_changes(comment=None)
        return updated_node

    def _is_docstring_expr(self, node: cst.CSTNode) -> bool:
        """Return True if the node is a single string-expression statement.

        Args:
            node: The CST node to check.

        Returns:
            True if the node represents a docstring expression.
        """
        if not isinstance(node, cst.SimpleStatementLine):
            return False
        if len(node.body) != 1:
            return False
        expr = node.body[0]
        if not isinstance(expr, cst.Expr):
            return False
        value = expr.value
        return m.matches(
            value,
            m.OneOf(
                m.SimpleString(),
                m.ConcatenatedString(),
            ),
        )

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.CSTNode | None:
        """Remove docstring statements.

        Args:
            original_node: The original node.
            updated_node: The updated node.

        Returns:
            The updated node, or RemovalSentinel to drop the statement.
        """
        if not self._is_docstring_expr(updated_node):
            return updated_node
        self.docstrings_removed += 1
        return cst.RemovalSentinel


def process_file(path: Path) -> tuple[Path, int, int, bool, str | None]:
    """Strip comments and non-module docstrings from a single Python file.

    Args:
        path: Path to the Python file to process.

    Returns:
        A tuple of (path, comments_removed, docstrings_removed, written, error).
    """
    text = path.read_text(encoding="utf-8")
    shebang = ""
    remainder = text
    if text.startswith("#!"):
        buf = io.StringIO(text)
        first_line = buf.readline()
        shebang = first_line
        remainder = buf.read()
    module_doc_range = find_module_docstring(remainder)
    module = cst.parse_module(remainder)
    transformer = StripCommentsAndDocstrings(module_doc_range)
    modified = module.visit(transformer)
    new_code = modified.code
    if shebang:
        new_code = shebang + new_code.lstrip("\n")
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            False,
            str(e),
        )
    path.write_text(new_code, encoding="utf-8")
    return (
        path,
        transformer.comments_removed,
        transformer.docstrings_removed,
        True,
        None,
    )


def iter_python_files_from_paths(paths: Iterable[Path]) -> list[Path]:
    """Expand paths into a list of Python files.

    Args:
        paths: Files and/or directories to scan.

    Returns:
        A list of paths to .py files.
    """
    result: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            result.append(p)
        elif p.is_dir():
            result.extend(q for q in p.rglob("*.py") if q.is_file())
    return result


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Strip comments and non-module docstrings from Python files."
    )
    parser.add_argument(
        "paths",
        type=Path,
        nargs="*",
        help=(
            "Files and/or directories to process. If omitted, '.' is used and searched recursively."
        ),
    )
    return parser.parse_args()


def _log_result(result: tuple[Path, int, int, bool, str | None]) -> None:
    """Log the outcome of processing a single file.

    Args:
        result: The tuple returned by process_file.
    """
    path, comments_removed, docstrings_removed, written, error = result
    if written:
        print(
            "{}: removed {} comments, {} docstrings",
            path,
            comments_removed,
            docstrings_removed,
        )
    else:
        logger.warning(
            "{}: INVALID after transform, skipped write (removed {} comments, {} docstrings). Error: {}",
            path,
            comments_removed,
            docstrings_removed,
            error,
        )


def main() -> None:
    """Entry point for the comment and docstring stripping script."""
    args = parse_args()
    input_paths: list[Path] = args.paths or [Path(".")]
    files = iter_python_files_from_paths(input_paths)
    if not files:
        print("No Python files found to process.")
        return

    with multiprocessing.Pool(processes=POOL_SIZE) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_file, (path,)) for path in files
        ]
        pool.close()
        pool.join()
        for async_result in async_results:
            result: tuple[Path, int, int, bool, str | None] = async_result.get()
            _log_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
