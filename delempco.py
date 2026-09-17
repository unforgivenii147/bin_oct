#!/data/data/com.termux/files/home/.local/bin/python
"""
Refactored blank line remover script. This is a parallel file processing tool that recursively
removes blank lines (and optionally whitespace-only lines) from text files. It uses
multiprocessing.Pool with a fixed pool of 8 workers, loguru for logging, pathlib for path
handling, and complete type annotations. The script detects binary files and skips them,
reports progress, and provides a summary of modified files, removed lines, and errors.
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from dh import is_binary, should_skip
from loguru import logger

# Module-level constants
ANSI_RESET: Final[str] = "\x1b[0m"
ANSI_BOLD: Final[str] = "\x1b[1m"
ANSI_DIM: Final[str] = "\x1b[2m"
ANSI_CYAN: Final[str] = "\x1b[36m"
ANSI_GREEN: Final[str] = "\x1b[32m"
ANSI_YELLOW: Final[str] = "\x1b[33m"
ANSI_RED: Final[str] = "\x1b[31m"

# Configuration
NUM_WORKERS: Final[int] = 8
MAX_PREVIEW_FILES: Final[int] = 5


class ANSI:
    """ANSI color codes for terminal output."""

    RESET: str = ANSI_RESET
    BOLD: str = ANSI_BOLD
    DIM: str = ANSI_DIM
    CYAN: str = ANSI_CYAN
    GREEN: str = ANSI_GREEN
    YELLOW: str = ANSI_YELLOW
    RED: str = ANSI_RED

    @classmethod
    def disable(cls) -> None:
        """Disable all ANSI color codes by setting them to empty strings."""
        for attr in dir(cls):
            if not attr.startswith("_") and attr != "disable":
                setattr(cls, attr, "")


@dataclass
class FileResult:
    """Result of processing a single file."""

    path: Path
    status: str
    total_lines: int = 0
    removed_lines: int = 0
    error_message: str = ""
    is_bin: bool = False


@dataclass
class ProcessingStats:
    """Statistics for the entire processing run."""

    total_files: int = 0
    text_files: int = 0
    binary_files: int = 0
    files_modified: int = 0
    lines_removed: int = 0
    errors_count: int = 0
    results: list[FileResult] = field(default_factory=list)


def remove_blank_lines(path: Path, remove_spaces: bool = False) -> tuple[int, int]:
    """
    Remove blank lines (and optionally whitespace-only lines) from a file.

    Args:
        path: Path to the file to process.
        remove_spaces: If True, also remove lines that contain only whitespace.

    Returns:
        A tuple of (total_lines, removed_lines).

    Raises:
        OSError: If the file cannot be read or written.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError as e:
        raise OSError(f"Failed to read file: {e}")

    total_lines: int = len(lines)

    if remove_spaces:
        filtered: list[str] = [line for line in lines if line.strip()]
    else:
        filtered = [line for line in lines if line not in ("\n", "\r\n", "\r")]

    removed_lines: int = total_lines - len(filtered)

    if removed_lines > 0:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(filtered)
        except OSError as e:
            raise OSError(f"Failed to write file: {e}")

    return (total_lines, removed_lines)


def process_file_worker(path: Path, remove_spaces: bool = False) -> FileResult:
    """
    Process a single file: detect binary, remove blank lines if text.

    Args:
        path: Path to the file to process.
        remove_spaces: If True, also remove whitespace-only lines.

    Returns:
        A FileResult describing the outcome.
    """
    result: FileResult = FileResult(path=path, status="error")

    try:
        try:
            with open(path, "rb") as f:
                first_8kb: bytes = f.read(8192)
        except OSError:
            result.status = "error"
            result.error_message = "Permission denied"
            return result

        if is_binary(path):
            result.status = "skipped_binary"
            result.is_bin = True
            return result

        total_lines, removed_lines = remove_blank_lines(path, remove_spaces)
        result.total_lines = total_lines
        result.removed_lines = removed_lines

        if removed_lines > 0:
            result.status = "processed"
        else:
            result.status = "unchanged"

    except OSError as e:
        result.status = "error"
        result.error_message = str(e)
    except Exception as e:
        result.status = "error"
        result.error_message = f"Unexpected error: {e}"

    return result


def discover_files(directories: list[str]) -> tuple[list[Path], int]:
    """
    Recursively discover files in the given directories, skipping unwanted ones.

    Args:
        directories: List of directory paths as strings.

    Returns:
        A tuple of (list of file paths, number of skipped directories).
    """
    files: list[Path] = []
    skipped_dirs: int = 0

    for dir_str in directories:
        dir_path = Path(dir_str).resolve()

        if not dir_path.exists():
            logger.warning(f"Directory not found: {dir_path}")
            skipped_dirs += 1
            continue

        if not dir_path.is_dir():
            logger.warning(f"Not a directory: {dir_path}")
            skipped_dirs += 1
            continue

        for path in dir_path.rglob("*"):
            if path.is_file() and not should_skip(path):
                files.append(path)

    return (files, skipped_dirs)


def print_header() -> None:
    """Log the application header banner."""
    print(f"{ANSI.CYAN}╔════════════════════════════════════════════╗{ANSI.RESET}")
    print(
        f"{ANSI.CYAN}║{ANSI.RESET}         Blank Line Remover              {ANSI.CYAN}║{ANSI.RESET}"
    )
    print(f"{ANSI.CYAN}╚════════════════════════════════════════════╝{ANSI.RESET}")


def print_directory_list(directories: list[str]) -> None:
    """
    Log the list of directories being processed.

    Args:
        directories: List of directory paths as strings.
    """
    print("Processing directories:")
    for dir_str in directories:
        print(f"  {ANSI.DIM}•{ANSI.RESET} {Path(dir_str).resolve()}")


def print_mode(remove_spaces: bool) -> None:
    """
    Log the current processing mode.

    Args:
        remove_spaces: If True, whitespace-only lines are also removed.
    """
    if remove_spaces:
        print(
            f"Mode: {ANSI.BOLD}Remove blank lines and whitespace-only lines{ANSI.RESET}"
        )
    else:
        print(f"Mode: {ANSI.BOLD}Remove blank lines only{ANSI.RESET}")


def print_separator() -> None:
    """Log a horizontal separator line."""
    print(f"{ANSI.CYAN}{'─' * 40}{ANSI.RESET}")


def print_results(stats: ProcessingStats, show_binary: bool = False) -> None:
    """
    Log detailed results: modified, unchanged, skipped binary, and errored files.

    Args:
        stats: Aggregated processing statistics.
        show_binary: If True, show all skipped binary files instead of a limited preview.
    """
    processed: list[FileResult] = [r for r in stats.results if r.status == "processed"]
    unchanged: list[FileResult] = [r for r in stats.results if r.status == "unchanged"]
    skipped_binary: list[FileResult] = [
        r for r in stats.results if r.status == "skipped_binary"
    ]
    errors: list[FileResult] = [r for r in stats.results if r.status == "error"]

    if processed:
        print(f"{ANSI.GREEN}✓ Modified files:{ANSI.RESET}")
        for result in sorted(processed, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.GREEN}●{ANSI.RESET} {rel_path}")
            print(
                f"    {ANSI.DIM}Lines: {result.total_lines}  →  Removed: {result.removed_lines}{ANSI.RESET}"
            )

    if unchanged:
        print(f"{ANSI.DIM}○ Unchanged files (no blank lines):{ANSI.RESET}")
        for result in sorted(unchanged, key=lambda r: r.path)[:MAX_PREVIEW_FILES]:
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.DIM}○ {rel_path}{ANSI.RESET}")
        if len(unchanged) > MAX_PREVIEW_FILES:
            print(
                f"  {ANSI.DIM}... and {len(unchanged) - MAX_PREVIEW_FILES} more{ANSI.RESET}"
            )

    if skipped_binary:
        print(f"{ANSI.YELLOW}⊘ Skipped binary files: {len(skipped_binary)}{ANSI.RESET}")
        preview: list[FileResult] = (
            skipped_binary
            if show_binary
            else sorted(skipped_binary, key=lambda r: r.path)[:MAX_PREVIEW_FILES]
        )
        for result in sorted(preview, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.YELLOW}⊘ {rel_path}{ANSI.RESET}")
        if not show_binary and len(skipped_binary) > MAX_PREVIEW_FILES:
            print(
                f"  {ANSI.YELLOW}... and {len(skipped_binary) - MAX_PREVIEW_FILES} more binary files{ANSI.RESET}"
            )

    if errors:
        print(f"{ANSI.RED}✗ Errors:{ANSI.RESET}")
        for result in sorted(errors, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            logger.error(f"  {ANSI.RED}✗ {rel_path}{ANSI.RESET}")
            logger.error(f"    {ANSI.DIM}{result.error_message}{ANSI.RESET}")


def print_summary(stats: ProcessingStats) -> None:
    """
    Log the final summary statistics.

    Args:
        stats: Aggregated processing statistics.
    """
    print_separator()
    print(f"{ANSI.BOLD}Summary:{ANSI.RESET}")
    print(f"  Total files found:     {ANSI.BOLD}{stats.total_files:,}{ANSI.RESET}")
    print(f"  Text files processed:  {ANSI.BOLD}{stats.text_files:,}{ANSI.RESET}")
    print(f"  Binary files skipped:  {ANSI.BOLD}{stats.binary_files:,}{ANSI.RESET}")
    print(
        f"  Files modified:        {ANSI.BOLD}{ANSI.GREEN}{stats.files_modified:,}{ANSI.RESET}"
    )
    print(
        f"  Lines removed:         {ANSI.BOLD}{ANSI.GREEN}{stats.lines_removed:,}{ANSI.RESET}"
    )
    if stats.errors_count > 0:
        print(
            f"  Errors:                {ANSI.BOLD}{ANSI.RED}{stats.errors_count:,}{ANSI.RESET}"
        )
    print_separator()


def main() -> int:
    """
    Entry point: parse arguments, discover files, process them in parallel,
    and report results.

    Returns:
        Exit code (0 if no errors, 1 otherwise).
    """
    parser = argparse.ArgumentParser(
        description="Recursively remove blank lines from text files with parallel processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python blank_remover.py\n\n\n  python blank_remover.py src/ tests/ docs/\n\n\n  python blank_remover.py src/ --space\n\n\n  python blank_remover.py . --show-binary\n        ",
    )
    parser.add_argument(
        "directories",
        nargs="*",
        default=["."],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "-s",
        "--space",
        action="store_true",
        help="Also remove lines containing only whitespace",
    )
    parser.add_argument(
        "--show-binary",
        action="store_true",
        help="Show all skipped binary files instead of just first 5",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI color codes"
    )
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        ANSI.disable()

    print_header()
    print_directory_list(args.directories)
    print_mode(args.space)

    print("Scanning for files... ")
    files, _skipped_dirs = discover_files(args.directories)
    print(f"Done! Found {ANSI.BOLD}{len(files):,}{ANSI.RESET} files.")

    if not files:
        logger.warning(f"{ANSI.YELLOW}No files found to process.{ANSI.RESET}")
        return 0

    print(
        f"Processing files...\n(Using {ANSI.BOLD}{NUM_WORKERS}{ANSI.RESET} worker processes)"
    )

    stats: ProcessingStats = ProcessingStats(total_files=len(files))
    start_time: float = time.time()
    processed_count: int = 0

    # Use multiprocessing.Pool with apply_async
    with Pool(processes=NUM_WORKERS) as pool:
        async_results: list[AsyncResult[FileResult]] = []
        for path in files:
            async_result: AsyncResult[FileResult] = pool.apply_async(
                process_file_worker, (path, args.space)
            )
            async_results.append(async_result)

        for async_result in async_results:
            result: FileResult = async_result.get()
            stats.results.append(result)
            processed_count += 1

            if result.status == "processed":
                stats.files_modified += 1
                stats.lines_removed += result.removed_lines
                stats.text_files += 1
            elif result.status == "unchanged":
                stats.text_files += 1
            elif result.status == "skipped_binary":
                stats.binary_files += 1
            elif result.status == "error":
                stats.errors_count += 1

    elapsed: float = time.time() - start_time

    print(
        f"  {ANSI.GREEN}Progress: Complete!{ANSI.RESET} ({ANSI.BOLD}{stats.text_files:,}{ANSI.RESET} text, {ANSI.BOLD}{stats.binary_files:,}{ANSI.RESET} binary)"
    )

    print_separator()
    print_results(stats, args.show_binary)
    print_summary(stats)
    print(f"Completed in {ANSI.DIM}{elapsed:.2f}s{ANSI.RESET}")

    return 0 if stats.errors_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
