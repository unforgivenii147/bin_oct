#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively compress or decompress files using Zstandard.

This script scans a directory tree (default: current directory), filters
files by extension (skipping already-compressed media/binary formats),
and compresses eligible files to ``<name>.zst`` or decompresses ``.zst``
files back to their original names. It uses a multiprocessing pool of 8
workers, tracks aggregate space statistics, and logs progress via loguru.

CLI:
    python script.py [-c|--compress] [-d|--decompress]
                     [--level 1-22] [--threads N] [--dir PATH] [--keep]
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import heapq
import json
import sys
import threading
from collections.abc import Generator, Iterator
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path

import zstandard as zstd
from dh import fsz
from loguru import logger

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

SKIP_EXTENSIONS_COMPRESS: set[str] = {
    ".xz",
    ".gz",
    ".7z",
    ".zip",
    ".whl",
    ".lz4",
    ".zst",
    ".br",
    ".bz2",
    ".lzma",
    ".z",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz2",
    ".bz3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".svg",
    ".ico",
    ".heic",
    ".heif",
    ".avif",
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".opus",
    ".mid",
    ".midi",
    ".aiff",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".iso",
    ".img",
    ".deb",
    ".rpm",
    ".pkg",
    ".msi",
}

VALID_DECOMPRESS_EXTENSIONS: set[str] = {".zst"}

SKIP_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".bin",
    "bin",
    "dh",
    "print_persian",
    ".dist-info",
    ".egg-info",
    "zstandard",
}

SKIP_DIR_PATTERNS: list[str] = ["*.egg-info", "*.dist-info"]

MEDIA_EXTENSIONS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".svg",
    ".ico",
    ".heic",
    ".heif",
    ".avif",
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".opus",
    ".mid",
    ".midi",
    ".aiff",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
}

WORKER_COUNT: int = 8
HEAP_SIZE_LIMIT: int = 10000
CHUNK_SIZE: int = 8192

# ---------------------------------------------------------------------------
# Statistics tracking
# ---------------------------------------------------------------------------


class SpaceStats:
    """Thread-safe accumulator for original vs. compressed byte counts."""

    original_size: int
    compressed_size: int
    lock: threading.Lock

    def __init__(self) -> None:
        """Initialize counters to zero and create a lock."""
        self.original_size = 0
        self.compressed_size = 0
        self.lock = threading.Lock()

    def add(self, original: int, compressed: int) -> None:
        """Add a pair of byte counts to the running totals."""
        with self.lock:
            self.original_size += original
            self.compressed_size += compressed

    def get_savings(self) -> tuple[int, float, float]:
        """Return (bytes_saved, ratio_percent, percent_saved)."""
        if self.original_size == 0:
            return 0, 0.0, 0.0
        saved = self.original_size - self.compressed_size
        ratio = self.compressed_size / self.original_size * 40
        percent_saved = saved / self.original_size * 40
        return saved, ratio, percent_saved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def should_skip_directory(dir_name: str) -> bool:
    """Return True if the directory name matches a skip rule."""
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


def is_editable_package_dir(root_path: Path) -> bool:
    """Detect editable-install package directories (egg-info + SOURCES.txt)."""
    try:
        for item in root_path.iterdir():
            if item.is_dir() and item.name.endswith(".egg-info"):
                if (item / "SOURCES.txt").exists():
                    return True
                direct_url = item / "direct_url.json"
                if direct_url.exists():
                    try:
                        with open(direct_url) as f:
                            data: dict[str, object] = json.load(f)
                            dir_info = data.get("dir_info")
                            if isinstance(dir_info, dict):
                                if dir_info.get("editable", False):
                                    return True
                    except (OSError, json.JSONDecodeError):
                        pass
        return False
    except (PermissionError, OSError):
        return False


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def get_files_generator(directory: Path, compress: bool) -> Generator[Path, None, None]:
    """Yield candidate files sorted largest-first via a bounded heap."""
    total_dirs = 0
    total_files = 0
    skipped_symlinks = 0
    skipped_extensions = 0
    skipped_editable = 0
    skipped_dirs = 0
    skipped_media = 0

    file_heap: list[tuple[int, Path]] = []

    for root, dirs, file_names in directory.walk():
        root_path = Path(root)
        if ".git" in root_path.parts:
            continue

        dirs_to_remove: list[str] = []
        for dir_name in dirs:
            if should_skip_directory(dir_name):
                dirs_to_remove.append(dir_name)
                skipped_dirs += 1
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)

        if is_editable_package_dir(root_path):
            dirs.clear()
            skipped_editable += 1
            continue

        total_dirs += 1

        for file_name in file_names:
            path = root_path / file_name
            if path.is_symlink():
                skipped_symlinks += 1
                continue

            path_str = str(path)
            if ".egg-info" in path_str or ".dist-info" in path_str:
                skipped_extensions += 1
                continue

            suffix = path.suffix.lower()

            if compress:
                if suffix in SKIP_EXTENSIONS_COMPRESS:
                    skipped_extensions += 1
                    if suffix in MEDIA_EXTENSIONS:
                        skipped_media += 1
                    continue
            else:
                if path.suffix not in VALID_DECOMPRESS_EXTENSIONS:
                    skipped_extensions += 1
                    continue

            try:
                file_size = path.stat().st_size
            except (OSError, PermissionError):
                skipped_extensions += 1
                continue

            heapq.heappush(file_heap, (-file_size, path))
            total_files += 1

            if len(file_heap) >= HEAP_SIZE_LIMIT:
                while file_heap:
                    _neg_size, fp = heapq.heappop(file_heap)
                    yield fp

    if skipped_symlinks > 0:
        logger.warning(f"Skipped {skipped_symlinks} symlinks")
    if skipped_media > 0:
        print(f"Skipped {skipped_media} media/binary files (already compressed)")
    if skipped_extensions > 0:
        print(f"Skipped {skipped_extensions} files with unwanted extensions")
    if skipped_editable > 0:
        print(f"Skipped {skipped_editable} editable package directories")
    if skipped_dirs > 0:
        print(f"Skipped {skipped_dirs} excluded directories")

    print(f"Sorting {total_files} files by size (largest first)...")
    while file_heap:
        _neg_size, fp = heapq.heappop(file_heap)
        yield fp

    print(f"Scanned {total_dirs} directories, found {total_files} files to process")


# ---------------------------------------------------------------------------
# Worker functions (must be top-level for multiprocessing pickling)
# ---------------------------------------------------------------------------


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int = 3,
    threads: int = 4,
    remove_original: bool = False,
) -> tuple[bool, Path, Path | str, int, int]:
    """Compress a single file to Zstandard. Returns a result tuple."""
    try:
        original_size = input_path.stat().st_size
        compressor = zstd.ZstdCompressor(level=level, threads=threads)
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = compressor.stream_reader(infile)
            while True:
                chunk = reader.read(CHUNK_SIZE)
                if not chunk:
                    break
                outfile.write(chunk)
        compressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return True, input_path, output_path, original_size, compressed_size
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def decompress_file(
    input_path: Path,
    output_path: Path,
    threads: int = 4,
    remove_original: bool = False,
) -> tuple[bool, Path, Path | str, int, int]:
    """Decompress a single ``.zst`` file. Returns a result tuple."""
    try:
        compressed_size = input_path.stat().st_size
        decompressor = zstd.ZstdDecompressor()
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = decompressor.stream_reader(infile)
            while True:
                chunk = reader.read(CHUNK_SIZE)
                if not chunk:
                    break
                outfile.write(chunk)
        decompressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return True, input_path, output_path, decompressed_size, compressed_size
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def process_files(
    file_generator: Iterator[Path],
    compress: bool,
    level: int = 3,
    threads: int = 4,
    remove_original: bool = False,
) -> None:
    """Dispatch all files through a multiprocessing pool and report results."""
    stats = SpaceStats()
    failed: list[tuple[Path, str]] = []
    skipped = 0
    completed = 0

    print(f"\n{'Compressing' if compress else 'Decompressing'} files...")
    print(f"Remove original files: {'Yes' if remove_original else 'No'}")
    print("-" * 40)

    files_list: list[Path] = list(file_generator)
    total_files = len(files_list)

    if total_files == 0:
        print("No files to process.")
        return

    print(f"Processing {total_files} files...")

    pending: list[tuple[AsyncResult, Path, Path]] = []

    with Pool(processes=WORKER_COUNT) as pool:
        for path in files_list:
            if compress:
                output_path = path.with_suffix(path.suffix + ".zst")
                if output_path.exists():
                    logger.warning(f"Skipping {path.name} - output already exists")
                    skipped += 1
                    completed += 1
                    continue
                async_result = pool.apply_async(
                    compress_file,
                    (path, output_path, level, threads, remove_original),
                )
            else:
                output_path = path.with_suffix("")
                if output_path.exists():
                    logger.warning(f"Skipping {path.name} - output already exists")
                    skipped += 1
                    completed += 1
                    continue
                async_result = pool.apply_async(
                    decompress_file,
                    (path, output_path, threads, remove_original),
                )
            pending.append((async_result, path, output_path))

        for async_result, path, _output_path in pending:
            try:
                result = async_result.get()
            except Exception as e:  # noqa: BLE001
                failed.append((path, str(e)))
                completed += 1
                continue

            success, path, _payload, orig_or_decomp, comp_or_in = result
            if compress:
                # orig_or_decomp is original size, comp_or_in is compressed size
                stats.add(orig_or_decomp, comp_or_in)
            else:
                # orig_or_decomp is decompressed size, comp_or_in is compressed size
                stats.add(orig_or_decomp, comp_or_in)

            completed += 1

            if not success:
                failed.append((path, str(_payload)))

    print("-" * 40)

    if compress and total_files > 0:
        saved, ratio, percent_saved = stats.get_savings()
        print("Compression Statistics:")
        print(f"   Original size:  {fsz(stats.original_size)}")
        print(f"   Compressed size: {fsz(stats.compressed_size)}")
        print(f"   Space saved:    {fsz(saved)} ({percent_saved:.1f}%)")
        print(f"   Compression ratio: {ratio:.1f}%")

    if skipped > 0:
        logger.warning(f"Skipped {skipped} files (already exist or invalid format)")

    if failed:
        logger.error(f"Failed to process {len(failed)} files:")
        for path, error in failed:
            logger.error(f"  - {path}: {error}")
    else:
        success_count = total_files - skipped
        if success_count > 0:
            logger.success(
                f"Successfully "
                f"{'compressed' if compress else 'decompressed'} "
                f"{success_count} files!"
            )
            if remove_original:
                print("   Original files have been removed.")
        else:
            logger.warning("No files were processed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse arguments and run the requested compression/decompression mode."""
    parser = argparse.ArgumentParser(
        description="Recursively compress or decompress files using Zstandard"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no action specified)",
    )
    group.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress files"
    )
    parser.add_argument(
        "--level",
        type=int,
        default=3,
        choices=range(1, 23),
        help="Compression level (1-22, default: 3)",
    )
    parser.add_argument(
        "--threads", type=int, default=4, help="Number of threads to use (default: 4)"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep original files (default: remove on success)",
    )
    args = parser.parse_args()

    if not args.compress and not args.decompress:
        args.compress = True
        print("No action specified, defaulting to compression mode")

    if args.compress and (args.level < 1 or args.level > 22):
        logger.error("Compression level must be between 1 and 22")
        return 1

    base_dir = Path(args.dir).resolve()
    if not base_dir.exists():
        logger.error(f"Directory '{base_dir}' does not exist")
        return 1
    if not base_dir.is_dir():
        logger.error(f"'{base_dir}' is not a directory")
        return 1

    remove_original = not args.keep

    print(f"Working directory: {base_dir}")
    print(f"Mode: {'Compression' if args.compress else 'Decompression'}")
    print(f"Threads: {args.threads}")
    if args.compress:
        print(f"Compression level: {args.level}")
    print(f"Keep original files: {'Yes' if args.keep else 'No'}")
    print("\nScanning directory tree...")

    file_generator = get_files_generator(base_dir, args.compress)
    process_files(
        file_generator, args.compress, args.level, args.threads, remove_original
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
