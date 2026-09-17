#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that compares two text files and reports the
lines unique to each file plus the number of common lines.

The generated script should:
- Accept two file paths as positional CLI arguments.
- Read both files line-by-line (using in-memory text reads), stripping
  leading/trailing spaces and tabs from lines when the file has a known
  source-code extension.
- Compute set differences and, for very large files (both over 10,000
  lines), shard the first file's lines into chunks and process the
  filtering step concurrently.
- Use multiprocessing.Pool.imap_unordered with a fixed pool of 8 workers
  (no CLI flag controls parallelism).
- Log the "only in <file>" lines and a final summary using loguru.
- Include complete type hints, docstrings on every function, and this
  module-level docstring.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Final, List, Optional, Tuple

from loguru import logger

POOL_SIZE: Final[int] = 8
LARGE_FILE_THRESHOLD: Final[int] = 10_000
MIN_CHUNK_SIZE: Final[int] = 1_000

CODE_EXT: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".sh",
        ".lua",
    }
)

FileLines = tuple[Path, list[str]]
DiffChunkArgs = tuple[list[str], "frozenset[str]", str]


def count_lines(path: Path) -> int:
    """Return the number of lines in ``path``.

    Args:
        path: File to count lines in.

    Returns:
        The line count (number of newline bytes plus one).
    """
    return path.read_bytes().count(b"\n") + 1


def strip_indentation(lines: Sequence[str]) -> list[str]:
    """Strip leading and trailing spaces/tabs from every line.

    Args:
        lines: Input lines.

    Returns:
        A new list of stripped lines.
    """
    return [line.strip(" \t") for line in lines]


def read_file_task(path: Path) -> FileLines:
    """Read ``path`` and return its lines, stripping code indentation.

    Args:
        path: File to read.

    Returns:
        A tuple ``(path, lines)``. For recognized source-code extensions,
        each line is stripped of leading/trailing spaces and tabs.
    """
    text: str = path.read_text(encoding="utf-8", errors="ignore")
    lines: list[str] = text.splitlines(keepends=False)
    if path.suffix.lower() in CODE_EXT:
        lines = strip_indentation(lines)
    return path, lines


def filter_diff_chunk(args: DiffChunkArgs) -> list[str]:
    """Filter a chunk of lines by membership in ``exclude_set``.

    Args:
        args: Tuple of ``(chunk, exclude_set, mode)`` where ``mode`` is
            ``"only_in_first"`` to keep lines NOT in ``exclude_set``, or any
            other value to keep lines that ARE in ``exclude_set``.

    Returns:
        The filtered list of lines.
    """
    chunk, exclude_set, mode = args
    if mode == "only_in_first":
        return [p for p in chunk if p not in exclude_set]
    return [p for p in chunk if p in exclude_set]


def _chunked(lines: list[str], size: int) -> list[list[str]]:
    """Split ``lines`` into contiguous chunks of at most ``size`` items.

    Args:
        lines: Lines to split.
        size: Maximum chunk size.

    Returns:
        A list of chunks.
    """
    return [lines[i : i + size] for i in range(0, len(lines), size)]


def report_diff_lines(path1: Path, path2: Path) -> None:
    """Compare ``path1`` and ``path2`` and log the diff summary.

    Args:
        path1: First file to compare.
        path2: Second file to compare.
    """
    lines1_count: int = count_lines(path1)
    lines2_count: int = count_lines(path2)

    with Pool(processes=POOL_SIZE) as pool:
        file_map: dict[Path, list[str]] = {}
        path: Path
        lines: list[str]
        for path, lines in pool.imap_unordered(read_file_task, [path1, path2]):
            file_map[path] = lines

    lines1: list[str] = file_map[path1]
    lines2: list[str] = file_map[path2]

    set1: set[str] = set(lines1)
    set2: set[str] = set(lines2)

    only_in_first: list[str]
    if lines1_count > LARGE_FILE_THRESHOLD and lines2_count > LARGE_FILE_THRESHOLD:
        chunk_size: int = max(MIN_CHUNK_SIZE, len(lines1) // POOL_SIZE)
        chunks: list[list[str]] = _chunked(lines1, chunk_size)
        frozen2: frozenset[str] = frozenset(set2)
        args_list: list[DiffChunkArgs] = [
            (chunk, frozen2, "only_in_first") for chunk in chunks
        ]
        only_in_first = []
        with Pool(processes=POOL_SIZE) as pool:
            partial: list[str]
            for partial in pool.imap_unordered(filter_diff_chunk, args_list):
                only_in_first.extend(partial)
    else:
        only_in_first = [p for p in lines1 if p not in set2]

    only_in_second: list[str] = [p for p in lines2 if p not in set1]
    common_count: int = len(set1 & set2)

    line: str
    if only_in_first:
        logger.info("only in {}:", path1.name)
        for line in only_in_first:
            logger.opt(colors=True).info("<green>  - {}</green>", line)

    if only_in_second:
        logger.info("only in {}:", path2.name)
        for line in only_in_second:
            logger.opt(colors=True).info("<yellow>  - {}</yellow>", line)

    logger.opt(colors=True).info(
        "<blue>common lines: {}\nonly in {}: {}\nonly in {}: {}</blue>",
        common_count,
        path1.name,
        len(only_in_first),
        path2.name,
        len(only_in_second),
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the file-diff script.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, 1 on invalid arguments).
    """
    args: list[str] = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 2:
        logger.error("Usage: python difflines.py <file1> <file2>")
        return 1
    f1: Path = Path(args[0])
    f2: Path = Path(args[1])
    report_diff_lines(f1, f2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
