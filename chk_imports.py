#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that scans a directory tree for `.py` files containing
import statements that are not located at the head of the file (i.e. after the
module docstring and initial import block), optionally autofixes them by moving
those imports to the top, writes a report, and uses loguru for logging,
pathlib for path handling, multiprocessing.Pool.apply_async with a fixed pool
of 8 workers for concurrency, and complete strict type annotations throughout.
"""

from __future__ import annotations

import argparse
import ast
from multiprocessing.pool import ApplyResult, Pool
from pathlib import Path
from typing import Final

from loguru import logger

POOL_SIZE: Final[int] = 8
DEFAULT_REPORT: Final[str] = "errors.txt"
SEPARATOR: Final[str] = "-" * 40
HEADER_SEPARATOR: Final[str] = "=" * 40

RESTRICTED_SCOPE_TYPES: Final[tuple[type[ast.AST], ...]] = (
    ast.Try,
    ast.If,
    ast.With,
    ast.AsyncWith,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.For,
    ast.AsyncFor,
    ast.While,
)

MisplacedImport = tuple[int, int, str]
ProcessResult = tuple[bool, bool, list[str]]


class ParentMapper(ast.NodeVisitor):
    """AST visitor that records the parent of every child node."""

    def __init__(self) -> None:
        """Initialize the parent mapping dictionary."""
        self.parents: dict[ast.AST, ast.AST] = {}

    def visit(self, node: ast.AST) -> None:
        """Record parents for all children of ``node`` then recurse."""
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
        self.generic_visit(node)


def get_ancestors(node: ast.AST, parent_map: dict[ast.AST, ast.AST]) -> list[ast.AST]:
    """Return the list of ancestors of ``node`` using ``parent_map``."""
    ancestors: list[ast.AST] = []
    current: ast.AST = node
    while current in parent_map:
        current = parent_map[current]
        ancestors.append(current)
    return ancestors


def is_in_restricted_scope(node: ast.AST, parent_map: dict[ast.AST, ast.AST]) -> bool:
    """Return True if ``node`` lies inside a restricted (non-top-level) scope."""
    ancestors = get_ancestors(node, parent_map)
    return any(isinstance(ancestor, RESTRICTED_SCOPE_TYPES) for ancestor in ancestors)


def find_imports_not_at_head(path: Path) -> list[MisplacedImport]:
    """Find imports in ``path`` that are not at the head of the module."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        logger.warning(f"[SKIP] {path}: Could not parse ({exc})")
        return []

    mapper = ParentMapper()
    mapper.visit(tree)
    parent_map = mapper.parents

    head_end_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            head_end_line = max(head_end_line, node.end_lineno or node.lineno)
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            head_end_line = max(head_end_line, node.end_lineno or node.lineno)
        else:
            break

    misplaced: list[MisplacedImport] = []
    lines = source.split("\n")
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if node.lineno <= head_end_line:
            continue
        if is_in_restricted_scope(node, parent_map):
            continue
        end_line = node.end_lineno or node.lineno
        import_text = "\n".join(lines[node.lineno - 1 : end_line])
        misplaced.append((node.lineno, end_line, import_text))
    return misplaced


def autofix_imports(path: Path, misplaced_imports: list[MisplacedImport]) -> bool:
    """Move the given misplaced imports to the head of ``path``."""
    if not misplaced_imports:
        return False

    source = path.read_text(encoding="utf-8")
    lines = source.split("\n")

    imports_to_move = [text for _start, _end, text in misplaced_imports]

    for line_num, end_line, _text in sorted(misplaced_imports, reverse=True):
        del lines[line_num - 1 : end_line]

    insert_index = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            insert_index = i + 1
        elif stripped.startswith(('"""', "'''")):
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                insert_index = i + 1
            else:
                quote_char = '"""' if '"""' in stripped else "'''"
                for j in range(i + 1, len(lines)):
                    if quote_char in lines[j]:
                        insert_index = j + 1
                        break
                break
        elif stripped.startswith(("import ", "from ")):
            insert_index = i + 1
        else:
            break

    new_lines = lines[:insert_index] + imports_to_move + [""] + lines[insert_index:]
    path.write_text("\n".join(new_lines), encoding="utf-8")
    return True


def process_file(path: Path, autofix: bool) -> ProcessResult:
    """Process a single file, returning (has_issues, was_fixed, details)."""
    misplaced = find_imports_not_at_head(path)
    if not misplaced:
        return False, False, []

    details: list[str] = []
    for line_num, _end_line, import_text in misplaced:
        detail = f"  Line {line_num}: {import_text.strip()}"
        print(detail)
        details.append(detail)

    if not autofix:
        return True, False, details

    if autofix_imports(path, misplaced):
        msg = f"  [FIXED] Moved {len(misplaced)} import(s) to top"
        print(msg)
        details.append(msg)
        return True, True, details

    msg = "  [ERROR] Failed to fix"
    logger.error(msg)
    details.append(msg)
    return True, False, details


def save_report(
    report_data: list[tuple[Path, list[str]]], output_file: str, autofix: bool
) -> None:
    """Write the scan report to ``output_file``."""
    path = Path(output_file)
    with path.open("w", encoding="utf-8") as handle:
        if not report_data:
            handle.write("No misplaced imports found! All files are clean.\n")
            return
        for path, details in report_data:
            handle.write(f"File: {path}\n")
            handle.write(f"{SEPARATOR}\n")
            handle.writelines(f"{detail}\n" for detail in details)
            handle.write("\n")
        if autofix:
            fixed = sum(
                1
                for _path, details in report_data
                if any("[FIXED]" in d for d in details)
            )
            handle.write(f"  Files fixed: {fixed}\n")
            handle.write(f"  Files with errors: {len(report_data) - fixed}\n")


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Find .py files with imports not at the head of the file"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically move misplaced imports to the top of the file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Save report to file",
    )
    return parser


def collect_files(root: Path) -> list[Path]:
    """Return the list of Python files to scan under ``root``."""
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(root.rglob("*.py"))


def main() -> int:
    """Entry point: parse arguments, scan files, report results."""
    parser = build_parser()
    args = parser.parse_args()

    output_file: str | None = args.output or (None if args.autofix else DEFAULT_REPORT)
    root = Path(args.directory)

    if not root.exists():
        logger.error(f"Directory '{root}' does not exist")
        return 1

    files = collect_files(root)
    if not files:
        logger.warning(f"No .py files found in '{root}'")
        return 0

    print(f"Scanning {len(files)} Python file(s) with {POOL_SIZE} worker(s)...")

    files_with_issues = 0
    files_fixed = 0
    report_data: list[tuple[Path, list[str]]] = []

    with Pool(processes=POOL_SIZE) as pool:
        async_results: list[tuple[Path, ApplyResult[ProcessResult]]] = [
            (fp, pool.apply_async(process_file, (fp, args.autofix))) for fp in files
        ]
        for path, result in async_results:
            has_issues, was_fixed, details = result.get()
            if has_issues:
                files_with_issues += 1
                report_data.append((path, details))
            if was_fixed:
                files_fixed += 1

    print(HEADER_SEPARATOR)
    print("Summary:")
    print(f"  Files with misplaced imports: {files_with_issues}")
    if args.autofix:
        print(f"  Files fixed: {files_fixed}")
    else:
        print("  Run with -a to autofix")

    if output_file and (files_with_issues > 0 or args.output):
        save_report(report_data, output_file, args.autofix)
        print(f"  Report saved to: {output_file}")

    if files_with_issues > 0 and not args.autofix:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
