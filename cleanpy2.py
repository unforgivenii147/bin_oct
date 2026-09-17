#!/data/data/com.termux/files/home/.local/bin/python
"""Remove comments and docstrings from Python files using libcst, preserving
shebangs, `# fmt:` / `# type:` comments, and module docstrings. Uses a
multiprocessing pool of 8 workers for parallel processing and logs progress
with loguru."""

from __future__ import annotations

import argparse
import multiprocessing
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final

import libcst as cst
from loguru import logger

NUM_WORKERS: Final[int] = 8
PRESERVED_PREFIXES: Final[tuple[str, ...]] = ("#!", "# fmt:", "# type:")
PRESERVED_SUBSTRINGS: Final[tuple[str, ...]] = ("# fmt:", "# type:")


class CleanTransformer(cst.CSTTransformer):
    """CST transformer that strips docstrings and comments from Python code."""

    comments_removed: int
    docstrings_removed: int

    def __init__(self) -> None:
        """Initialize the transformer with zeroed removal counters."""
        super().__init__()
        self.comments_removed = 0
        self.docstrings_removed = 0

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        """Return the module unchanged; module docstrings are preserved."""
        return updated_node

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        """Strip the docstring from a function definition if present."""
        return self._strip_docstring(updated_node)

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef:
        """Strip the docstring from a class definition if present."""
        return self._strip_docstring(updated_node)

    def _strip_docstring(
        self,
        node: cst.FunctionDef | cst.ClassDef,
    ) -> cst.FunctionDef | cst.ClassDef:
        """Remove a leading string-literal docstring from the given node.

        If the body becomes empty after removal, a `pass` statement is
        inserted to keep the body syntactically valid.
        """
        body = node.body.body
        if not body:
            return node

        first_stmt = body[0]
        if (
            isinstance(first_stmt, cst.SimpleStatementLine)
            and len(first_stmt.body) == 1
            and isinstance(first_stmt.body[0], cst.Expr)
        ):
            expr_value = first_stmt.body[0].value
            if isinstance(expr_value, (cst.SimpleString, cst.ConcatenatedString)):
                self.docstrings_removed += 1
                remaining = list(body[1:])
                if remaining:
                    new_body = node.body.with_changes(body=remaining)
                else:
                    new_body = node.body.with_changes(
                        body=[cst.SimpleStatementLine(body=[cst.Pass()])]
                    )
                return node.with_changes(body=new_body)

        return node

    def leave_Comment(
        self,
        original_node: cst.Comment,
        updated_node: cst.Comment,
    ) -> cst.RemovalSentinel | cst.Comment:
        """Drop comments unless they are shebangs, `# fmt:`, or `# type:`."""
        comment_text = original_node.value.strip()
        if comment_text.startswith(PRESERVED_PREFIXES) or any(
            marker in comment_text for marker in PRESERVED_SUBSTRINGS
        ):
            return updated_node

        self.comments_removed += 1
        return cst.RemoveFromParent()


def process_file(path: Path) -> tuple[Path, int, int, bool]:
    """Parse, transform, and rewrite a single Python file.

    Returns a tuple of (path, comments_removed, docstrings_removed, success).
    """
    try:
        original_source = path.read_text(encoding="utf-8")
        module = cst.parse_module(original_source)
        transformer = CleanTransformer()
        modified_module = module.visit(transformer)
        new_source = modified_module.code

        if new_source == original_source:
            return path, 0, 0, True

        path.write_text(new_source, encoding="utf-8", newline="\n")
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error processing {path}: {exc}")
        return path, 0, 0, False


def collect_python_files(paths: list[str]) -> list[Path]:
    """Expand CLI paths into a sorted, de-duplicated list of `.py` files."""
    py_files: list[Path] = []
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
        else:
            logger.warning(f"Skipping non-existent path: {path}")
    return sorted(set(py_files))


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Remove comments & docstrings from Python files "
            "(preserves shebangs, # fmt, # type, module docstrings)"
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    return parser


def main() -> int:
    """Entry point: parse args, process files in a pool of 8 workers."""
    parser = build_arg_parser()
    args = parser.parse_args()

    py_files = collect_python_files(args.paths)
    if not py_files:
        print("No Python files found.")
        return 0

    print(f"Found {len(py_files)} Python files to process...")

    total_comments = 0
    total_docstrings = 0
    processed = 0

    with Pool(processes=NUM_WORKERS) as pool:
        async_results: list[AsyncResult[tuple[Path, int, int, bool]]] = [
            pool.apply_async(process_file, (f,)) for f in py_files
        ]
        for result in async_results:
            path, comments, docstrings, success = result.get()
            processed += 1
            if not success:
                continue

            total_comments += comments
            total_docstrings += docstrings
            if comments or docstrings:
                logger.success(
                    f"{path.name:<30} removed "
                    f"{comments:>2} comments, {docstrings:>2} docstrings"
                )
            else:
                print(f"{path.name:<30} (no changes)")

    print("=" * 40)
    logger.success("Finished!")
    print(f"Files processed   : {processed}")
    print(f"Comments removed  : {total_comments}")
    print(f"Docstrings removed: {total_docstrings}")
    print("-" * 40)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
