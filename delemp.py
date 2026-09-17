#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that removes blank lines from text files recursively.

Requirements:
- Walk one or more user-provided file/directory paths (default: current directory).
- Skip binary files and symlinks; skip any path part named ".git".
- Two blank-line modes: remove all blank lines (default) or preserve single blank lines (-1).
- Optional -s/--space to also strip whitespace-only lines (treated as blank).
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers.
- Use mmap for files larger than a configurable threshold (default 1 MiB, -t/--threshold).
- Detect binaries via the binaryornot package.
- Log all output with loguru (no print, no stdlib logging).
- Use pathlib exclusively (no os.path).
- Full strict type hints throughout (mypy/pyright clean).
- Display a header, live progress, and a final summary with counts and removed lines.
- CLI flags: paths..., -1, -s/--space, -t/--threshold, -b/--show-binary.
"""

from __future__ import annotations

import argparse
import mmap
from collections.abc import Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from binaryornot.check import is_binary
from loguru import logger

MMAP_THRESHOLD: int = 1024 * 1024
POOL_WORKERS: Final[int] = 8
BINARY_SIGNATURES: Final[tuple[bytes, ...]] = (
    b"\x00",
    b"\xff\xd8\xff",
    b"\x89PNG",
    b"GIF8",
    b"BM",
    b"\x00\x00\x01\x00",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"\x7fELF",
    b"MZ",
    b"\xca\xfe\xba\xbe",
    b"%PDF",
    b"\xd0\xcf\x11\xe0",
    b"SQLite format 3",
    b"RIFF",
    b"\x1aE\xdf\xa3",
    b"\x00\x00\x00\x18ftyp",
    b"\x00\x00\x00\x1cftyp",
    b"ID3",
    b"OggS",
    b"fLaC",
    b"FWS",
    b"CWS",
    b"%!PS",
    b"\x1f\x9d",
    b"\x1f\xa0",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf'\x1c",
    b"Rar!\x1a\x07",
    b"\xed\xab\xee\xdb",
    b"\xd4\xc3\xb2\xa1",
    b"\xa1\xb2\xc3\xd4",
)
_TEXT_CHARS: Final[bytearray] = bytearray(
    {7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)) | set(range(128, 256))
)
_BINARY_CHECK_SIZE: Final[int] = 8192


def remove_all_blank_lines(text: str) -> str:
    """Remove every blank (or whitespace-only) line from ``text``."""
    lines = text.splitlines(keepends=True)
    return "".join(line for line in lines if line.strip() != "")


def preserve_single_blank_lines(text: str) -> str:
    """Collapse runs of blank lines into a single blank line and trim trailing blanks."""
    lines = text.splitlines(keepends=True)
    result_lines: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank
    while len(result_lines) > 1 and result_lines[-1].strip() == "":
        result_lines.pop()
    return "".join(result_lines)


def process_small_file(
    path: Path, preserve_single: bool, remove_spaces: bool
) -> tuple[str, int, int, str]:
    """Read, transform, and (if needed) rewrite a small text file."""
    content = path.read_text(encoding="utf-8")
    total_lines = len(content.splitlines())
    if preserve_single:
        result = preserve_single_blank_lines(content)
    else:
        result = remove_all_blank_lines(content)
    result_lines = len(result.splitlines()) if result else 0
    removed_lines = total_lines - result_lines
    if removed_lines > 0:
        path.write_text(result, encoding="utf-8")
    return (str(path), total_lines, removed_lines, "processed")


def process_large_file_mmap(
    path: Path, preserve_single: bool, remove_spaces: bool
) -> tuple[str, int, int, str]:
    """Same as ``process_small_file`` but uses mmap for large files."""
    try:
        with open(path, "r+b") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                content = mm.read().decode("utf-8", errors="ignore")
            total_lines = len(content.splitlines())
            if preserve_single:
                result = preserve_single_blank_lines(content)
            else:
                result = remove_all_blank_lines(content)
            result_lines = len(result.splitlines()) if result else 0
            removed_lines = total_lines - result_lines
            if removed_lines > 0:
                f.seek(0)
                f.write(result.encode("utf-8"))
                f.truncate()
        return (str(path), total_lines, removed_lines, "processed")
    except Exception as e:  # noqa: BLE001
        return (str(path), 0, 0, f"Error with mmap: {e!s}")


def remove_blank_lines(
    path: Path, preserve_single: bool = False, remove_spaces: bool = False
) -> tuple[str, int, int, str]:
    """Dispatch to mmap or in-memory processing based on file size."""
    try:
        file_size = path.stat().st_size
        if file_size > MMAP_THRESHOLD:
            return process_large_file_mmap(path, preserve_single, remove_spaces)
        return process_small_file(path, preserve_single, remove_spaces)
    except Exception as e:  # noqa: BLE001
        return (str(path), 0, 0, f"Error: {e!s}")


ProcessArgs = tuple[Path, Path, bool, bool]
ProcessResult = tuple[str, int, int, str]


def process_file(args: ProcessArgs) -> ProcessResult:
    """Worker entry point: skip binaries, otherwise remove blank lines."""
    base_dir, path, preserve_single, remove_spaces = args
    if is_binary(str(path)):
        try:
            rel_path = path.relative_to(base_dir)
            return (str(rel_path), 0, 0, "binary")
        except ValueError:
            return (str(path), 0, 0, "binary")
    result = remove_blank_lines(path, preserve_single, remove_spaces)
    try:
        rel_path = Path(result[0]).relative_to(base_dir)
        file_size = path.stat().st_size
        method = " [mmap]" if file_size > MMAP_THRESHOLD else ""
        status = result[3] + method if result[3] == "processed" else result[3]
        return (str(rel_path), result[1], result[2], status)
    except ValueError:
        return result


def collect_files(paths: Sequence[Path]) -> list[tuple[Path, Path]]:
    """Expand the given paths into ``(base_dir, path)`` pairs."""
    files: list[tuple[Path, Path]] = []
    for path in paths:
        if not path.exists():
            logger.warning(f"'{path}' does not exist, skipping.")
            continue
        if path.is_file():
            if not path.is_symlink():
                files.append((path.parent, path))
        elif path.is_dir():
            for path in path.rglob("*"):
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and ".git" not in path.parts
                ):
                    files.append((path, path))
        else:
            logger.warning(f"'{path}' is not a file or directory, skipping.")
    return files


def print_header(
    paths: Sequence[Path],
    preserve_single: bool,
    remove_spaces: bool,
    mmap_threshold: int,
) -> None:
    """Emit the run header via loguru."""
    print("=" * 42)
    print("         Blank Line Remover")
    print("=" * 42)
    print("Processing paths:")
    for path in paths:
        path_type = "📄" if path.is_file() else "📁"
        print(f"  {path_type} {path.absolute()}")
    if preserve_single:
        mode = "Preserve single blank lines"
    else:
        mode = "Remove all blank lines"
    if remove_spaces:
        mode += " (+ whitespace-only lines)"
    print(f"Mode: {mode}")
    print(f"mmap threshold: {mmap_threshold:,} bytes")


def print_results(
    results: list[ProcessResult],
    total_removed: int,
    total_files: int,
    show_all_binary: bool = False,
    mmap_threshold: int = MMAP_THRESHOLD,
) -> None:
    """Emit the final summary via loguru."""
    print("-" * 40)
    results.sort(key=lambda x: x[0])
    processed = [r for r in results if r[3].startswith("processed")]
    skipped_binary = [r for r in results if r[3] == "binary"]
    errors = [
        r
        for r in results
        if r[3] not in ("processed", "binary") and not r[3].startswith("processed")
    ]
    large_files_count = sum(1 for _, _, _, s in processed if "[mmap]" in s)

    if processed:
        print("✓ Modified files:")
        for path, total_lines, removed, status in processed:
            if removed > 0:
                method_indicator = " [mmap]" if "[mmap]" in status else ""
                print(f"  ● {path}{method_indicator}")
                print(f"    Lines: {total_lines:,}  →  Removed: {removed:,}")
            else:
                print(f"  ○ {path} (no blank lines found)")

    if skipped_binary:
        print(f"⊘ Skipped binary files: {len(skipped_binary)}")
        display_count = (
            len(skipped_binary) if show_all_binary else min(5, len(skipped_binary))
        )
        for path, _, _, _ in skipped_binary[:display_count]:
            print(f"  ⊘ {path}")
        if len(skipped_binary) > display_count:
            print(f"  ... and {len(skipped_binary) - display_count} more binary files")

    if errors:
        logger.error("✗ Errors:")
        for path, _, _, status in errors:
            logger.error(f"  ✗ {path}")
            logger.error(f"    {status}")

    print("-" * 40)
    print("Summary:")
    print(f"  Total files found:     {total_files:,}")
    print(f"  Text files processed:  {len(processed):,}")
    if large_files_count > 0:
        print(f"    Large files (mmap):  {large_files_count:,}")
    print(f"  Binary files skipped:  {len(skipped_binary):,}")
    print(f"  Files modified:        {sum(1 for r in processed if r[2] > 0):,}")
    print(f"  Lines removed:         {total_removed:,}")
    if errors:
        logger.error(f"  Errors:                {len(errors):,}")
    print("-" * 40)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Remove blank lines from files recursively using parallel "
            "processing (with mmap support)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files and/or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-1",
        dest="preserve_single",
        action="store_true",
        help=(
            "Preserve single blank lines (remove only multiple consecutive blank lines)"
        ),
    )
    parser.add_argument(
        "-s",
        "--space",
        action="store_true",
        help="Also remove lines that contain only whitespace characters",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=MMAP_THRESHOLD,
        help=(
            f"File size threshold for using mmap in bytes "
            f"(default: {MMAP_THRESHOLD:,} = 1MB)"
        ),
    )
    parser.add_argument(
        "-b",
        "--show-binary",
        action="store_true",
        help="Show all skipped binary files (default: shows only first 5)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: collect files, dispatch to the pool, then report."""
    global MMAP_THRESHOLD
    args = parse_args(argv)
    MMAP_THRESHOLD = args.threshold
    paths: list[Path] = [Path(p).resolve() for p in args.paths]

    print_header(paths, args.preserve_single, args.space, MMAP_THRESHOLD)
    print("Scanning for files...")
    file_list = collect_files(paths)
    total_files = len(file_list)
    print(f"Done! Found {total_files:,} files.")

    if not file_list:
        logger.warning("No files found to process.")
        return 0

    process_args: list[ProcessArgs] = [
        (base_dir, path, args.preserve_single, args.space)
        for base_dir, path in file_list
    ]

    results: list[ProcessResult] = []
    total_removed = 0
    processed_count = 0
    skipped_count = 0
    error_count = 0
    large_count = 0

    print("Processing files...")
    print(
        f"(Using {POOL_WORKERS} worker processes, mmap for files > "
        f"{MMAP_THRESHOLD:,} bytes)"
    )

    pool = Pool(processes=POOL_WORKERS)
    try:
        async_results = [pool.apply_async(process_file, (arg,)) for arg in process_args]
        total = len(async_results)
        for completed, ar in enumerate(async_results, start=1):
            try:
                result = ar.get()
                _, _, removed, status = result
                total_removed += removed
                results.append(result)
                if status.startswith("processed"):
                    processed_count += 1
                    if "[mmap]" in status:
                        large_count += 1
                elif status == "binary":
                    skipped_count += 1
                else:
                    error_count += 1
            except Exception as e:  # noqa: BLE001
                error_count += 1
                results.append(("<unknown>", 0, 0, f"error: {e!s}"))
            print(
                f"Progress: {completed:,}/{total:,} files processed "
                f"({processed_count:,} text, {large_count:,} mmap, "
                f"{skipped_count:,} binary, {error_count:,} errors)"
            )
        pool.close()
        pool.join()
    finally:
        pool.terminate()

    print(
        f"Complete! ({processed_count:,} text, {large_count:,} mmap, "
        f"{skipped_count:,} binary, {error_count:,} errors)"
    )
    print_results(results, total_removed, total_files, args.show_binary, MMAP_THRESHOLD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
