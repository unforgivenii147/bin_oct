#!/data/data/com.termux/files/home/.local/bin/python
"""Remove comments from non-binary text files by scanning a directory tree.

This module scans a directory for non-binary files, removes Python-style
``#`` comments from each file (preserving strings and multi-line string
literals), and writes the modified content back. It uses a fixed-size
``multiprocessing.Pool`` of 8 workers for parallelism, ``loguru`` for
logging, and ``pathlib`` for all path handling. Files with known binary
extensions, hidden files/directories, common VCS/build directories, and
files larger than 10 MiB are skipped by default. A ``--dry-run`` mode
lists candidate files without modifying them, and ``--include-hidden``,
``--no-ignore-extensions``, and ``--exclude-dirs`` control filtering.

Example:
    python remove_comments.py /path/to/project --verbose
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from dh import is_binary
from loguru import logger

EXCLUDE_EXTENSIONS: Final[set[str]] = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".class",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".min.js",
    ".min.css",
}

DEFAULT_EXCLUDE_DIRS: Final[set[str]] = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".tox",
    ".eggs",
    ".idea",
    ".vscode",
    "vendor",
    "bower_components",
}

MAX_FILE_SIZE_BYTES: Final[int] = 10 * 1024 * 1024
POOL_SIZE: Final[int] = 8

ProcessResult = tuple[Path, int, str | None, bool]


def remove_comments_from_content(content: str) -> tuple[str, int]:
    """Remove ``#`` comments from source text while preserving string literals.

    Args:
        content: The full text content of a file.

    Returns:
        A tuple ``(modified_content, removed_count)`` where ``modified_content``
        is the text with comments stripped and ``removed_count`` is the number
        of comment lines/segments that were removed.
    """
    lines: list[str] = content.split("\n")
    modified_lines: list[str] = []
    removed_count: int = 0
    in_multiline_string: bool = False
    string_delimiter: str | None = None

    for line in lines:
        if in_multiline_string:
            modified_lines.append(line)
            if string_delimiter is not None and string_delimiter in line:
                in_multiline_string = False
                string_delimiter = None
            continue

        if '"""' in line or "'''" in line:
            for delim in ('"""', "'''"):
                if delim in line:
                    if line.count(delim) % 2 == 1:
                        in_multiline_string = not in_multiline_string
                        string_delimiter = delim if in_multiline_string else None
                    modified_lines.append(line)
                    break
            continue

        stripped: str = line.strip()
        if not stripped:
            modified_lines.append(line)
            continue

        if stripped.startswith("#"):
            removed_count += 1
            modified_lines.append("")
            continue

        quote_char: str | None = None
        comment_pos: int = -1
        for i, char in enumerate(line):
            if char in ('"', "'"):
                if quote_char is None:
                    quote_char = char
                elif quote_char == char:
                    quote_char = None
            elif char == "#" and quote_char is None:
                comment_pos = i
                break

        if comment_pos != -1:
            before_comment: str = line[:comment_pos].strip()
            removed_count += 1
            if before_comment:
                modified_lines.append(line[:comment_pos].rstrip())
            else:
                modified_lines.append("")
        else:
            modified_lines.append(line)

    return "\n".join(modified_lines), removed_count


def is_ignored_extension(path: Path) -> bool:
    """Return ``True`` if the file has an extension in ``EXCLUDE_EXTENSIONS``.

    Also checks the last two suffixes combined (e.g. ``.min.js``).

    Args:
        path: Path to the file to test.

    Returns:
        ``True`` if the file should be skipped based on its extension.
    """
    suffix: str = path.suffix.lower()
    if suffix in EXCLUDE_EXTENSIONS:
        return True
    suffixes: list[str] = path.suffixes
    if len(suffixes) > 1:
        double_suffix: str = "".join(suffixes[-2:]).lower()
        if double_suffix in EXCLUDE_EXTENSIONS:
            return True
    return False


def is_hidden(path: Path) -> bool:
    """Return ``True`` if any part of the path starts with a dot.

    Args:
        path: Path to inspect.

    Returns:
        ``True`` if the path contains a hidden component.
    """
    return any(part.startswith(".") for part in path.parts)


def process_file(path: Path) -> ProcessResult:
    """Process a single file: detect binary, strip comments, write back.

    Args:
        path: Path to the file to process.

    Returns:
        A tuple ``(path, removed_count, error_message, was_binary)``. When
        ``was_binary`` is ``True`` the file was skipped as binary. When
        ``error_message`` is not ``None`` an error occurred while processing.
    """
    try:
        if is_binary(str(path)):
            return path, 0, None, True

        original_content: str = path.read_text(encoding="utf-8")
        modified_content: str
        removed_count: int
        modified_content, removed_count = remove_comments_from_content(original_content)

        if removed_count > 0:
            path.write_text(modified_content, encoding="utf-8")

        return path, removed_count, None, False
    except UnicodeDecodeError:
        return path, 0, "Unable to read as text file (encoding issue)", True
    except Exception as exc:  # noqa: BLE001
        return path, 0, str(exc), False


def find_target_files(
    root_dir: Path,
    include_hidden: bool = False,
    exclude_dirs: set[str] | None = None,
    ignore_extensions: bool = True,
) -> list[Path]:
    """Recursively find candidate files for comment removal.

    Args:
        root_dir: Root directory to scan.
        include_hidden: Whether to include hidden files and directories.
        exclude_dirs: Directory names to skip. Defaults to ``DEFAULT_EXCLUDE_DIRS``.
        ignore_extensions: Whether to skip files with binary/ignored extensions.

    Returns:
        A list of ``Path`` objects for candidate files.
    """
    if exclude_dirs is None:
        exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)

    target_files: list[Path] = []
    for path in root_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(excluded in path.parts for excluded in exclude_dirs):
            continue
        if not include_hidden and is_hidden(path):
            continue
        if ignore_extensions and is_ignored_extension(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                continue
        except OSError:
            continue
        target_files.append(path)

    return target_files


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Remove comments from non-binary files using # comment syntax"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to process (default: current directory)",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories (starting with .)",
    )
    parser.add_argument(
        "--no-ignore-extensions",
        action="store_true",
        help="Process files with typically ignored extensions",
    )
    parser.add_argument(
        "--exclude-dirs",
        nargs="+",
        help="Additional directories to exclude",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed processing information",
    )
    return parser


def _iter_results(
    results: Iterable[ProcessResult],
    total: int,
    root_dir: Path,
    verbose: bool,
) -> tuple[int, int, int, int, int]:
    """Aggregate results and log per-file progress.

    Args:
        results: Iterable of ``ProcessResult`` tuples.
        total: Total number of files being processed.
        root_dir: Root directory used for relative path display.
        verbose: Whether to log per-file details for skipped/unchanged files.

    Returns:
        Tuple ``(total_removed, files_changed, files_with_errors,
        binary_files, completed)``.
    """
    total_removed: int = 0
    files_changed: int = 0
    files_with_errors: int = 0
    binary_files: int = 0
    completed: int = 0

    for path, removed, error, was_binary in results:
        completed += 1
        try:
            rel: Path = path.relative_to(root_dir)
        except ValueError:
            rel = path

        if was_binary:
            binary_files += 1
            if verbose:
                logger.debug("[{}/{}] Skipped binary: {}", completed, total, rel)
        elif error:
            logger.error("[{}/{}] Error: {}: {}", completed, total, rel, error)
            files_with_errors += 1
        elif removed > 0:
            print(
                "[{}/{}] Removed {} comment(s): {}",
                completed,
                total,
                removed,
                rel,
            )
            total_removed += removed
            files_changed += 1
        else:
            if verbose:
                logger.debug("[{}/{}] No changes: {}", completed, total, rel)

    return total_removed, files_changed, files_with_errors, binary_files, completed


def main() -> int:
    """Entry point: parse arguments and process files in parallel.

    Returns:
        Exit code (0 on success, 1 on fatal error).
    """
    parser: argparse.ArgumentParser = _build_parser()
    args: argparse.Namespace = parser.parse_args()

    root_dir: Path = Path(args.directory).resolve()
    if not root_dir.exists():
        logger.error("Directory '{}' does not exist", root_dir)
        return 1

    exclude_dirs: set[str] = set(DEFAULT_EXCLUDE_DIRS)
    if args.exclude_dirs:
        exclude_dirs.update(args.exclude_dirs)

    print("Scanning directory: {}", root_dir)
    print("Finding non-binary files...")

    target_files: list[Path] = find_target_files(
        root_dir,
        include_hidden=bool(args.include_hidden),
        exclude_dirs=exclude_dirs,
        ignore_extensions=not bool(args.no_ignore_extensions),
    )

    if not target_files:
        print("No files found to process.")
        return 0

    print("Found {} file(s) to check", len(target_files))

    if args.dry_run:
        print("[Dry Run] Would check these files:")
        for f in sorted(target_files)[:20]:
            print("  {}", f.relative_to(root_dir))
        if len(target_files) > 20:
            print("  ... and {} more files", len(target_files) - 20)
        return 0

    total_removed: int = 0
    files_changed: int = 0
    files_with_errors: int = 0
    binary_files: int = 0

    print("Processing files in parallel with {} workers...", POOL_SIZE)

    results: list[ProcessResult] = []
    try:
        with Pool(processes=POOL_SIZE) as pool:
            async_results = [
                pool.apply_async(process_file, (path,)) for path in target_files
            ]
            for async_result in async_results:
                try:
                    results.append(async_result.get())
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected error in worker: {}", exc)
                    files_with_errors += 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130

    (
        total_removed,
        files_changed,
        files_with_errors_extra,
        binary_files,
        _completed,
    ) = _iter_results(results, len(target_files), root_dir, bool(args.verbose))
    files_with_errors += files_with_errors_extra

    print("{}", "=" * 40)
    print("Summary:")
    print("  Files scanned: {}", len(target_files))
    print("  Binary files skipped: {}", binary_files)
    print("  Files changed: {}", files_changed)
    print("  Total comments removed: {}", total_removed)
    if files_with_errors > 0:
        print("  Files with errors: {}", files_with_errors)
    print("{}", "=" * 40)

    return 0


if __name__ == "__main__":
    sys.exit(main())
