#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python script that scans the top 5 lines of every .py file in the
current directory (excluding itself) in parallel using multiprocessing.Pool with
8 workers, removes an automated module docstring of the form
 if found, and validates the modified source with
ast.parse before writing it back to disk. Use loguru for logging, pathlib for
all path handling, full type annotations, and multiprocessing.Pool.apply_async.
"""

from __future__ import annotations

import ast
import re
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final

from loguru import logger

# --------------------------------------------------------------------------- #
# Module-level constants
# --------------------------------------------------------------------------- #

MAX_WORKERS: Final[int] = 8
SCAN_LIMIT: Final[int] = 5


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #


def _build_pattern(file_name: str) -> re.Pattern[str]:
    """Build the regex that matches the automated module docstring.

    Args:
        file_name: The base name of the file whose docstring should be matched.

    Returns:
        A compiled regular expression matching the automated docstring line.
    """
    return re.compile(rf'^\s*"""\s*Module for\s+{re.escape(file_name)}\s*\.?\s*"""\s*$')


def _validate_source(source: str) -> bool:
    """Return True if *source* is syntactically valid Python.

    Args:
        source: The Python source code to validate.

    Returns:
        True when the source parses successfully, False otherwise.
    """
    try:
        ast.parse(source)
    except SyntaxError as exc:
        logger.warning("AST validation failed: {}", exc)
        return False
    return True


# --------------------------------------------------------------------------- #
# Core worker
# --------------------------------------------------------------------------- #


def clean_single_file(path: Path) -> None:
    """Remove an automated module docstring from a single Python file.

    Reads the file, searches the first :data:`SCAN_LIMIT` lines for a matching
    automated docstring, removes it if present, validates the resulting source
    with :func:`ast.parse`, and writes the file back only when the source is
    valid.

    Args:
        path: Path to the Python file to process.
    """
    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        logger.error("Error reading {}: {}", path.name, exc)
        return

    if not lines:
        print("Skipped empty file: {}", path.name)
        return

    pattern: re.Pattern[str] = _build_pattern(path.name)
    scan_limit: int = min(SCAN_LIMIT, len(lines))
    removed_index: int | None = None

    for i in range(scan_limit):
        if pattern.match(lines[i].strip()):
            lines.pop(i)
            removed_index = i
            break

    if removed_index is None:
        print(
            "No automated docstring in top {} lines of: {}",
            SCAN_LIMIT,
            path.name,
        )
        return

    new_source: str = "".join(lines)
    if not _validate_source(new_source):
        logger.error(
            "Refusing to write {}: modified source failed AST validation",
            path.name,
        )
        return

    try:
        path.write_text(new_source, encoding="utf-8")
    except OSError as exc:
        logger.error("Error writing {}: {}", path.name, exc)
        return

    logger.success(
        "Cleaned docstring from line {} of: {}", removed_index + 1, path.name
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    """Run the parallel cleanup over all Python files in the current directory.

    Returns:
        Process exit code (0 on success).
    """
    current_dir: Path = Path(".")
    self_name: str = Path(__file__).name
    py_files: list[Path] = [f for f in current_dir.glob("*.py") if f.name != self_name]

    if not py_files:
        logger.warning("No Python files found in the current directory.")
        return 0

    print(
        "Scanning the top {} lines of {} files with {} workers...",
        SCAN_LIMIT,
        len(py_files),
        MAX_WORKERS,
    )

    pool: Pool = Pool(processes=MAX_WORKERS)
    try:
        async_results = [
            pool.apply_async(clean_single_file, (py_file,)) for py_file in py_files
        ]
        for async_result in async_results:
            async_result.get()
    finally:
        pool.close()
        pool.join()

    logger.success("Fast cleanup complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
