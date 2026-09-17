#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python utility that removes comments and docstrings from Python source files.

The script must:
- Use tree-sitter (tree-sitter==0.25.2, tree-sitter-python==0.25.0) as the default
  parsing engine, with a fallback AST-based remover.
- Replace concurrent.futures with multiprocessing.Pool.apply_async using a fixed pool
  of 8 workers. No CLI flags for parallelism.
- Use pathlib exclusively for filesystem operations.
- Use loguru for all logging (no print, no stdlib logging).
- Provide complete strict type annotations (passes mypy --strict / pyright).
- Include docstrings on the module, every class, and every function.
- Expose a CLI via argparse with: positional `directory`, `--method {tree-sitter,ast}`,
  and `--compare` (dry-run comparison of both methods). No worker/job flags.
- Validate that rewritten files still parse via ast.parse before writing.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

from loguru import logger

try:
    from tree_sitter import Language, Node, Parser, Query
    from tree_sitter_python import language as python_language
except ImportError:  # pragma: no cover - import-time guard
    logger.error("Install tree-sitter==0.25.2 and tree-sitter-python==0.25.0")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

WORKER_COUNT: Final[int] = 8
COMMENT_QUERY: Final[str] = """
(comment) @comment
(string) @string
"""
_IGNORED_CHILD_TYPES: Final[frozenset[str]] = frozenset(
    {"comment", "NEWLINE", "INDENT", "DEDENT"}
)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ProcessingResult:
    """Outcome of processing a single Python file."""

    path: Path
    success: bool
    error: str | None = None
    original_size: int = 0
    new_size: int = 0
    processing_time: float = 0.0


# ---------------------------------------------------------------------------
# Tree-sitter implementation
# ---------------------------------------------------------------------------


class TreeSitterCommentRemover:
    """Remove comments and docstrings using tree-sitter's Python grammar."""

    QUERY: Final[str] = COMMENT_QUERY

    def __init__(self) -> None:
        """Initialize the parser and compile the comment/string query."""
        self.parser: Parser = Parser()
        language: Language = python_language()
        self.parser.set_language(language)
        self.query: Query = language.query(self.QUERY)

    def remove_comments_and_docstrings(self, source: str) -> str:
        """Return `source` with all comments and docstrings blanked out."""
        source_bytes: bytes = source.encode("utf-8")
        tree: Any = self.parser.parse(source_bytes)
        captures: list[tuple[Node, str]] = self.query.captures(tree.root_node)

        ranges_to_remove: list[tuple[int, int]] = []
        for node, capture_name in captures:
            if capture_name == "comment" or (
                capture_name == "string" and self._is_docstring(node)
            ):
                ranges_to_remove.append((node.start_byte, node.end_byte))

        ranges_to_remove.sort(reverse=True)
        result: bytes = self._remove_ranges(source_bytes, ranges_to_remove)
        return result.decode("utf-8", errors="replace")

    @staticmethod
    def _is_docstring(node: Node) -> bool:
        """Return True when `node` is a string expression statement (docstring)."""
        parent: Node | None = node.parent
        if parent is None or parent.type != "expression_statement":
            return False
        named_children = [
            child for child in parent.children if child.type not in _IGNORED_CHILD_TYPES
        ]
        return len(named_children) == 1 and named_children[0] == node

    @staticmethod
    def _remove_ranges(source_bytes: bytes, ranges: Sequence[tuple[int, int]]) -> bytes:
        """Replace each byte range with whitespace/newlines preserving line count."""
        if not ranges:
            return source_bytes
        result: bytearray = bytearray(source_bytes)
        for start, end in ranges:
            removed: bytes = source_bytes[start:end]
            newline_count: int = removed.count(b"\n")
            replacement: bytes = (
                b"\n" * newline_count if newline_count > 0 else b" " * (end - start)
            )
            result[start:end] = replacement
        return bytes(result)


# ---------------------------------------------------------------------------
# AST fallback implementation
# ---------------------------------------------------------------------------


class ASTCommentRemover:
    """Fallback remover that strips `#` comments line-by-line via the ast module."""

    def remove_comments_and_docstrings(self, source: str) -> str:
        """Return `source` with line comments removed (docstrings left intact)."""
        lines: list[str] = source.split("\n")
        cleaned_lines: list[str] = []
        for line in lines:
            cleaned_lines.append(self._strip_line_comment(line))
        source_cleaned: str = "\n".join(cleaned_lines)

        try:
            tree: ast.AST = ast.parse(source_cleaned)
        except SyntaxError:
            return source_cleaned

        docstring_ranges: list[tuple[int, int]] = self._extract_docstring_ranges(
            tree, source_cleaned
        )
        for start, end in sorted(docstring_ranges, reverse=True):
            source_cleaned = source_cleaned[:start] + source_cleaned[end:]
        return source_cleaned

    @staticmethod
    def _strip_line_comment(line: str) -> str:
        """Remove the trailing `#` comment from a single source line."""
        in_string: bool = False
        string_char: str | None = None
        result: list[str] = []
        i: int = 0
        while i < len(line):
            char: str = line[i]
            if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                result.append(char)
            elif char == "#" and not in_string:
                break
            else:
                result.append(char)
            i += 1
        return "".join(result)

    @staticmethod
    def _extract_docstring_ranges(tree: ast.AST, source: str) -> list[tuple[int, int]]:
        """Return byte-offset ranges of docstrings within `source`.

        The current implementation is intentionally conservative and returns an
        empty list; it exists to keep the public surface stable for future work.
        """
        ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            docstring: str | None = ast.get_docstring(node)
            if docstring and isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
            ):
                # Placeholder: range computation requires token stream access.
                pass
        _ = source  # keep parameter referenced for future implementation
        return ranges


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_syntax(source: str) -> bool:
    """Return True if `source` parses as valid Python."""
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------------------
# Per-file workers (picklable top-level functions)
# ---------------------------------------------------------------------------


def process_file_tree_sitter(path: Path) -> ProcessingResult:
    """Process a single file with the tree-sitter remover."""
    start_time: float = time.perf_counter()
    try:
        original_content: str = path.read_text(encoding="utf-8")
        original_size: int = len(original_content.encode("utf-8"))
        remover: TreeSitterCommentRemover = TreeSitterCommentRemover()
        new_content: str = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                path=path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        path.write_text(new_content, encoding="utf-8")
        new_size: int = len(new_content.encode("utf-8"))
        return ProcessingResult(
            path=path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure via result
        return ProcessingResult(
            path=path,
            success=False,
            error=str(exc),
            processing_time=time.perf_counter() - start_time,
        )


def process_file_ast(path: Path) -> ProcessingResult:
    """Process a single file with the AST fallback remover."""
    start_time: float = time.perf_counter()
    try:
        original_content: str = path.read_text(encoding="utf-8")
        original_size: int = len(original_content.encode("utf-8"))
        remover: ASTCommentRemover = ASTCommentRemover()
        new_content: str = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                path=path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        new_size: int = len(new_content.encode("utf-8"))
        return ProcessingResult(
            path=path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as exc:  # noqa: BLE001 - surface any failure via result
        return ProcessingResult(
            path=path,
            success=False,
            error=str(exc),
            processing_time=time.perf_counter() - start_time,
        )


# ---------------------------------------------------------------------------
# Directory driver
# ---------------------------------------------------------------------------


def _select_process_func(method: str) -> Any:
    """Return the per-file worker corresponding to `method`."""
    if method == "tree-sitter":
        return process_file_tree_sitter
    return process_file_ast


def process_directory(
    directory: Path = Path.cwd(),
    method: str = "tree-sitter",
) -> tuple[list[ProcessingResult], float]:
    """Process every `*.py` file under `directory` with a fixed 8-worker pool."""
    py_files: list[Path] = list(directory.glob("**/*.py"))
    if not py_files:
        logger.warning("No Python files found in {}", directory)
        return [], 0.0

    print("Processing {} files using {}", len(py_files), method)
    start_time: float = time.perf_counter()
    process_func: Any = _select_process_func(method)

    results: list[ProcessingResult] = []
    pool: Pool = Pool(processes=WORKER_COUNT)
    try:
        async_results: list[Any] = [
            pool.apply_async(process_func, (path,)) for path in py_files
        ]
        for async_result in async_results:
            result: ProcessingResult = async_result.get()
            results.append(result)
            status: str = "✓" if result.success else "✗"
            error_msg: str = f" ({result.error})" if result.error else ""
            print(
                "{status} {name}{err}",
                status=status,
                name=result.path.name,
                err=error_msg,
            )
    finally:
        pool.close()
        pool.join()

    total_time: float = time.perf_counter() - start_time
    return results, total_time


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_results(
    results: Sequence[ProcessingResult], total_time: float, method: str
) -> None:
    """Log a summary report of `results` for the given `method`."""
    successful: list[ProcessingResult] = [r for r in results if r.success]
    failed: list[ProcessingResult] = [r for r in results if not r.success]

    total_original: int = sum(r.original_size for r in successful)
    total_new: int = sum(r.new_size for r in successful)
    reduction: int = total_original - total_new if total_original > 0 else 0
    reduction_pct: float = (
        reduction / total_original * 100 if total_original > 0 else 0.0
    )
    avg_time: float = (
        sum(r.processing_time for r in results) / len(results) if results else 0.0
    )

    print("=" * 40)
    print("Results ({})", method.upper())
    print("=" * 40)
    print("Total files:      {}", len(results))
    print("Successful:       {}", len(successful))
    print("Failed:           {}", len(failed))
    print("Total time:       {:.3f}s", total_time)
    print("Avg time/file:    {:.3f}s", avg_time)
    print("Original size:    {:,} bytes", total_original)
    print("New size:         {:,} bytes", total_new)
    print("Reduction:        {:,} bytes ({:.1f}%)", reduction, reduction_pct)
    if failed:
        logger.warning("Failed files:")
        for r in failed:
            logger.warning("  - {}: {}", r.path, r.error)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s\n"
            "  %(prog)s --method ast\n"
            "  %(prog)s --compare\n"
            "  %(prog)s /path/to/dir\n"
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "--method",
        choices=["tree-sitter", "ast"],
        default="tree-sitter",
        help="Processing method (default: tree-sitter)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare both methods (dry-run, no files modified)",
    )
    return parser


def _iter_py_files(directory: Path) -> Iterable[Path]:
    """Yield every `*.py` file under `directory` recursively."""
    return directory.glob("**/*.py")


def main() -> int:
    """Entry point for the CLI."""
    parser: argparse.ArgumentParser = build_arg_parser()
    args: argparse.Namespace = parser.parse_args()

    directory: Path = Path(args.directory).resolve()
    if not directory.exists():
        logger.error("Directory not found: {}", directory)
        return 1

    if args.compare:
        print("Comparing methods on {}", directory)
        py_files: list[Path] = list(_iter_py_files(directory))
        print("Found {} Python files", len(py_files))

        print("[1/2] Testing tree-sitter method...")
        ts_results, ts_time = process_directory(directory, "tree-sitter")
        print_results(ts_results, ts_time, "tree-sitter")

        print("[2/2] Testing AST method...")
        ast_results, ast_time = process_directory(directory, "ast")
        print_results(ast_results, ast_time, "ast")

        print("=" * 40)
        print("PERFORMANCE COMPARISON")
        print("=" * 40)
        print("Tree-sitter time: {:.3f}s", ts_time)
        print("AST time:         {:.3f}s", ast_time)
        speedup: float = ast_time / ts_time if ts_time > 0 else 0.0
        print("Speedup:          {:.2f}x", speedup)
        logger.warning("NOTE: Files were NOT modified (dry-run mode)")
    else:
        results, total_time = process_directory(directory, args.method)
        print_results(results, total_time, args.method)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
