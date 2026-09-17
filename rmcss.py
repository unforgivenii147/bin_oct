#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that recursively removes HTML comments (<!-- ... -->)
from HTML, HTM, and CSS files within a directory. The script should:

- Accept a target directory (default: current directory) and a list of file
  extensions to process (default: .html, .htm, .css).
- Recursively discover matching files using pathlib.
- Strip all HTML comments using a compiled regex with re.DOTALL.
- Only rewrite files whose content actually changes.
- Process files concurrently using multiprocessing.Pool.apply_async with a
  fixed pool of 8 workers (no CLI flag for parallelism).
- Use loguru for all logging output.
- Include complete type annotations, docstrings on all functions, and a
  module-level docstring.
- Return exit code 0 on success, 1 on fatal error.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import Optional, Set, Tuple

from loguru import logger

COMMENT_PATTERN: re.Pattern[str] = re.compile(r"<!--.*?-->", re.DOTALL)
DEFAULT_EXTENSIONS: tuple[str, ...] = (".html", ".htm", ".css")
POOL_SIZE: int = 8

FileResult = tuple[Path, bool, str | None]


def remove_comments_from_file(file_path: Path) -> FileResult:
    """Remove HTML comments from a single file.

    Args:
        file_path: Path to the file to process.

    Returns:
        A tuple of (file_path, was_updated, error_message). ``error_message``
        is ``None`` on success, or a string describing the failure.
    """
    try:
        content: str = file_path.read_text(encoding="utf-8", errors="ignore")
        new_content: str = COMMENT_PATTERN.sub("", content)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8", errors="ignore")
            return (file_path, True, None)
        return (file_path, False, None)
    except Exception as exc:  # noqa: BLE001
        return (file_path, False, str(exc))


def find_files(directory: Path, extensions: set[str]) -> Iterator[Path]:
    """Yield files under ``directory`` whose suffix matches ``extensions``.

    Args:
        directory: Root directory to search recursively.
        extensions: Set of lowercase file extensions (with leading dot).

    Yields:
        Matching file paths.

    Raises:
        ValueError: If ``directory`` does not exist.
    """
    if not directory.exists():
        raise ValueError(f"Directory {directory} does not exist")
    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            yield file_path


def _normalize_extension(ext: str) -> str:
    """Normalize an extension to lowercase with a leading dot.

    Args:
        ext: Raw extension string, with or without a leading dot.

    Returns:
        Normalized extension, e.g. ``".html"``.
    """
    ext = ext.lower()
    return ext if ext.startswith(".") else f".{ext}"


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Remove HTML comments from HTML and CSS files recursively."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to process (default: .html .htm .css)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the comment-removal CLI.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, 1 on fatal error).
    """
    parser: argparse.ArgumentParser = _build_parser()
    args: argparse.Namespace = parser.parse_args(
        list(argv) if argv is not None else None
    )

    extensions: set[str] = {_normalize_extension(ext) for ext in args.extensions}
    directory: Path = Path(args.directory)

    try:
        files = list(find_files(directory, extensions))
    except ValueError as exc:
        logger.error("{}", exc)
        return 1

    if not files:
        logger.info("No files found with extensions: {}", ", ".join(extensions))
        return 0

    logger.info("Found {} files to process", len(files))
    logger.info("Using {} workers", POOL_SIZE)
    logger.info("{}", "-" * 40)

    updated_count: int = 0
    error_count: int = 0

    try:
        with Pool(processes=POOL_SIZE) as pool:
            async_results = [
                (file_path, pool.apply_async(remove_comments_from_file, (file_path,)))
                for file_path in files
            ]
            for file_path, async_result in async_results:
                _, was_updated, error = async_result.get()
                try:
                    rel_path: Path = file_path.relative_to(directory)
                except ValueError:
                    rel_path = file_path
                if error:
                    logger.error("ERROR: {} - {}", rel_path, error)
                    error_count += 1
                elif was_updated:
                    logger.info("UPDATED: {}", rel_path)
                    updated_count += 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fatal error: {}", exc)
        return 1

    logger.info("{}", "-" * 40)
    logger.info("Summary:")
    logger.info("  Total files processed: {}", len(files))
    logger.info("  Files updated: {}", updated_count)
    logger.info("  Errors: {}", error_count)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
