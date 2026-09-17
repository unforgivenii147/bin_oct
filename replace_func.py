#!/data/data/com.termux/files/home/.local/bin/python
"""
Refactored script to remove a hardcoded code block from Python files and replace it with an import.

This script scans Python files for a specific code block (read from ~/lic), removes it,
and ensures that `from dh import cprint` is imported. It uses multiprocessing for parallel
file processing, loguru for logging, pathlib for path handling, and is fully type-annotated.

Key features:
- Reads the target code block from ~/lic (instead of a hardcoded string).
- Removes the block from files if found, and inserts the cprint import if not already present.
- Uses a multiprocessing Pool with 8 workers.
- Logs all actions with loguru.
- Skips the script itself and files with syntax errors after modification.
"""

from __future__ import annotations

import ast
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIC_PATH: Final[Path] = Path.home() / "lic"
IMPORT_LINE: Final[str] = "from dh import cprint\n"
POOL_SIZE: Final[int] = 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_code_block() -> list[str]:
    """Read the code block from ~/lic and return its lines (rstripped)."""
    try:
        content = LIC_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"Failed to read {LIC_PATH}: {e}")
        raise
    # Normalize: strip trailing whitespace on each line, keep as list
    return [line.rstrip() for line in content.strip("\n").splitlines()]


def find_block_range(
    lines: list[str], block_lines: list[str]
) -> tuple[int, int] | None:
    """
    Find the range (start, end) of the block in the given lines.

    Args:
        lines: The file content split into lines (with or without newlines).
        block_lines: The normalized block lines to search for.

    Returns:
        A tuple (start, end) where start is the index of the first block line
        and end is the index after the last block line, or None if not found.
    """
    normalized = [line.rstrip("\n").rstrip() for line in lines]
    n, m = len(normalized), len(block_lines)
    for i in range(n - m + 1):
        if normalized[i : i + m] == block_lines:
            return (i, i + m)
    return None


def already_imports_cprint(tree: ast.Module) -> bool:
    """Check if the AST already contains an import of cprint from dh or bare cprint."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "dh":
            if any(alias.name == "cprint" for alias in node.names):
                return True
        if isinstance(node, ast.Import) and any(
            alias.name == "cprint" for alias in node.names
        ):
            return True
    return False


def last_import_end_line(tree: ast.Module) -> int:
    """
    Return the end line number of the last top-level import statement.

    If no imports are found, returns 0.
    """
    last_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.end_lineno is not None:
                last_end = max(last_end, node.end_lineno)
        else:
            break
    return last_end


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def process_file(path: Path) -> None:
    """
    Process a single Python file: remove the code block and add the import.

    Args:
        path: Path to the Python file.
    """
    path = Path(path)
    if path.resolve() == Path(__file__).resolve():
        return

    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        logger.warning(f"Skipping {path}: {e}")
        return

    block_lines = load_code_block()
    lines = content.splitlines(keepends=True)
    match = find_block_range(lines, block_lines)
    if match is None:
        return

    start, end = match
    # Extend to include surrounding blank lines
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1
    if end < len(lines) and lines[end].strip() == "":
        end += 1

    del lines[start:end]
    new_content = "".join(lines)

    # Verify syntax
    try:
        tree = ast.parse(new_content)
    except SyntaxError as e:
        logger.warning(f"Skipping write for {path} (would break syntax): {e}")
        return

    # If cprint already imported, just write the block removal
    if already_imports_cprint(tree):
        if new_content != content:
            path.write_text(new_content, encoding="utf-8")
            print(f"Removed block: {path} (cprint already imported)")
        return

    # Otherwise insert the import line
    body_lines = new_content.splitlines(keepends=True)
    last_end = last_import_end_line(tree)
    if last_end > 0:
        insert_idx = last_end
    else:
        insert_idx = 1 if body_lines and body_lines[0].startswith("#!") else 0

    body_lines.insert(insert_idx, IMPORT_LINE)
    final_content = "".join(body_lines)
    path.write_text(final_content, encoding="utf-8")
    print(f"Removed block and added import: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point: gather files and process them in parallel."""
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        py_files = [Path(p) for p in args]
    else:
        # Import here to avoid circular import at module level if needed
        from dh import get_pyfiles  # type: ignore[import]

        py_files = get_pyfiles(cwd)

    with Pool(POOL_SIZE) as pool:
        # apply_async for each file; we don't need results, but we should wait
        async_results = [pool.apply_async(process_file, (path,)) for path in py_files]
        for ar in async_results:
            try:
                ar.get()
            except Exception as e:
                logger.error(f"Error processing file: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
