#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively compress or decompress files using Zstandard.

This script walks a directory tree, compresses files with zstandard
(skipping already-compressed and media formats) or decompresses .zst
files, using a multiprocessing pool of 8 workers. It supports
configurable compression level, thread count per compression call,
keeping originals, and reports space savings. Uses loguru for logging,
pathlib for path handling, and full type annotations.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import sys
from collections.abc import Generator, Iterable
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any

import zstandard as zstd
from dh import fsz
from loguru import logger

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

POOL_WORKERS: int = 8
CHUNK_SIZE: int = 8192
PROGRESS_BAR_WIDTH: int = 50


class SpaceStats:
    """Thread-safe accumulator for original vs compressed byte counts."""

    original_size: int
    compressed_size: int

    def __init__(self) -> None:
        """Initialize counters to zero."""
        self.original_size = 0
        self.compressed_size = 0

    def add(self, original: int, compressed: int) -> None:
        """Add byte counts to the running totals."""
        self.original_size += original
        self.compressed_size += compressed

    def get_savings(self) -> tuple[int, float, float]:
        """
        Return (saved_bytes, ratio, percent_saved).

        Ratio and percent_saved are scaled to a 40-point scale
        to match the original implementation's behavior.
        """
        if self.original_size == 0:
            return 0, 0.0, 0.0
        saved = self.original_size - self.compressed_size
        ratio = self.compressed_size / self.original_size * 40
        percent_saved = saved / self.original_size * 40
        return saved, ratio, percent_saved


class WalkStats:
    """Mutable counters collected while walking the directory tree."""

    dirs: int
    files: int
    skipped_symlinks: int
    skipped_extensions: int
    skipped_editable: int
    skipped_dirs: int
    skipped_media: int

    def __init__(self) -> None:
        """Initialize all counters to zero."""
        self.dirs = 0
        self.files = 0
        self.skipped_symlinks = 0
        self.skipped_extensions = 0
        self.skipped_editable = 0
        self.skipped_dirs = 0
        self.skipped_media = 0


def should_skip_directory(dir_name: str) -> bool:
    """Return True if the directory name matches any skip rule."""
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


def is_editable_package_dir(root_path: Path) -> bool:
    """
    Return True if root_path contains an editable-install egg-info dir.

    Detects either a SOURCES.txt file or a direct_url.json with
    dir_info.editable set to True.
    """
    try:
        for item in root_path.iterdir():
            if item.is_dir() and item.name.endswith(".egg-info"):
                if (item / "SOURCES.txt").exists():
                    return True
                direct_url = item / "direct_url.json"
                if direct_url.exists():
                    try:
                        with open(direct_url) as f:
                            data: dict[str, Any] = json.load(f)
                        if data.get("dir_info", {}).get("editable", False):
                            return True
                    except (OSError, ValueError):
                        pass
        return False
    except (PermissionError, OSError):
        return False


def walk_files(directory: Path, compress: bool) -> Generator[Path, None, None]:
    """
    Yield files under `directory` that should be processed.

    When `compress` is True, skips files with already-compressed or
    media extensions. When False, yields only .zst files.
    Prints summary warnings about skipped items at the end.
    """
    stats = WalkStats()

    for root, dirs, files in directory.walk():
        root_path = Path(root)
        if ".git" in root_path.parts:
            continue

        dirs_to_remove: list[str] = []
        for dir_name in dirs:
            if should_skip_directory(dir_name):
                dirs_to_remove.append(dir_name)
                stats.skipped_dirs += 1
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)

        if is_editable_package_dir(root_path):
            dirs.clear()
            stats.skipped_editable += 1
            continue

        stats.dirs += 1

        for file_name in files:
            path = root_path / file_name

            if path.is_symlink():
                stats.skipped_symlinks += 1
                continue

            if ".egg-info" in str(path) or ".dist-info" in str(path):
                stats.skipped_extensions += 1
                continue

            if compress:
                if path.suffix.lower() in SKIP_EXTENSIONS_COMPRESS:
                    stats.skipped_extensions += 1
                    if path.suffix.lower() in MEDIA_EXTENSIONS:
                        stats.skipped_media += 1
                    continue
            elif path.suffix not in VALID_DECOMPRESS_EXTENSIONS:
                stats.skipped_extensions += 1
                continue

            stats.files += 1
            yield path

    if stats.skipped_symlinks > 0:
        logger.warning(f"⚠️  Skipped {stats.skipped_symlinks} symlinks")
    if stats.skipped_media > 0:
        print(
            f"ℹ️  Skipped {stats.skipped_media} media/binary files (already compressed)"
        )
    if stats.skipped_extensions > 0:
        print(f"ℹ️  Skipped {stats.skipped_extensions} files with unwanted extensions")
    if stats.skipped_editable > 0:
        print(f"ℹ️  Skipped {stats.skipped_editable} editable package directories")
    if stats.skipped_dirs > 0:
        print(f"ℹ️  Skipped {stats.skipped_dirs} excluded directories")
    print(f"Scanned {stats.dirs} directories, found {stats.files} files to process")


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int,
    threads: int,
    remove_original: bool,
) -> tuple[bool, Path, str, int, int]:
    """
    Compress a single file from input_path to output_path.

    Returns (success, input_path, output_or_error, original_size, compressed_size).
    On failure, cleans up partial output and returns the error string.
    """
    try:
        original_size = input_path.stat().st_size
        compressor = zstd.ZstdCompressor(level=level, threads=threads)
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = compressor.stream_reader(infile)
            outfile.writelines(iter(lambda: reader.read(CHUNK_SIZE), b""))
        compressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return True, input_path, str(output_path), original_size, compressed_size
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def decompress_file(
    input_path: Path,
    output_path: Path,
    threads: int,
    remove_original: bool,
) -> tuple[bool, Path, str, int, int]:
    """
    Decompress a single .zst file from input_path to output_path.

    Returns (success, input_path, output_or_error, decompressed_size,
    compressed_size). On failure, cleans up partial output and returns
    the error string.
    """
    try:
        compressed_size = input_path.stat().st_size
        decompressor = zstd.ZstdDecompressor()
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = decompressor.stream_reader(infile)
            outfile.writelines(iter(lambda: reader.read(CHUNK_SIZE), b""))
        decompressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return (
            True,
            input_path,
            str(output_path),
            decompressed_size,
            compressed_size,
        )
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def _process_results(
    results: Iterable[tuple[bool, Path, str, int, int]],
    stats: SpaceStats,
    failed: list[tuple[Path, str]],
    total: int,
    skipped: int,
    compress: bool,
    remove_original: bool,
) -> None:
    """Iterate over completed results, update stats, and print progress."""
    processed = skipped
    for result in results:
        success, input_path, output_or_error, original_size, compressed_size = result
        processed += 1
        progress = int(processed / total * PROGRESS_BAR_WIDTH) if total else 0
        bar = "█" * progress + "░" * (PROGRESS_BAR_WIDTH - progress)
        print(
            f"\rProgress: [{bar}] {processed}/{total} files",
            end="",
            flush=True,
        )
        if success:
            stats.add(original_size, compressed_size)
        else:
            failed.append((input_path, output_or_error))


def process_files(
    file_generator: Iterable[Path],
    compress: bool,
    level: int,
    threads: int,
    remove_original: bool,
) -> None:
    """
    Dispatch all files to a multiprocessing pool for compression or
    decompression, then report statistics and failures.
    """
    stats = SpaceStats()
    failed: list[tuple[Path, str]] = []
    skipped = 0

    print("Counting files...")
    files_list: list[Path] = list(file_generator)
    total = len(files_list)

    if total == 0:
        print("No files to process.")
        return

    print(f"{'Compressing' if compress else 'Decompressing'} {total} files...")
    print(f"Remove original files: {'Yes' if remove_original else 'No'}")
    print("-" * 40)

    pool = Pool(processes=POOL_WORKERS)
    async_results: list[AsyncResult[tuple[bool, Path, str, int, int]]] = []

    try:
        for path in files_list:
            if compress:
                output_path = path.with_suffix(path.suffix + ".zst")
                if output_path.exists():
                    logger.warning(f"⚠️  Skipping {path.name} - output already exists")
                    skipped += 1
                    continue
                async_results.append(
                    pool.apply_async(
                        compress_file,
                        (path, output_path, level, threads, remove_original),
                    )
                )
            else:
                output_path = path.with_suffix("")
                if output_path.exists():
                    logger.warning(f"⚠️  Skipping {path.name} - output already exists")
                    skipped += 1
                    continue
                async_results.append(
                    pool.apply_async(
                        decompress_file,
                        (path, output_path, threads, remove_original),
                    )
                )

        pool.close()
        results = (ar.get() for ar in async_results)
        _process_results(
            results,
            stats,
            failed,
            total,
            skipped,
            compress,
            remove_original,
        )
        pool.join()
    except BaseException:
        pool.terminate()
        pool.join()
        raise

    print()
    print("-" * 40)

    if compress and total > 0:
        saved, ratio, percent_saved = stats.get_savings()
        print("📊 Compression Statistics:")
        print(f"   Original size:   {fsz(stats.original_size)}")
        print(f"   Compressed size: {fsz(stats.compressed_size)}")
        print(f"   Space saved:     {fsz(saved)} ({percent_saved:.1f}%)")
        print(f"   Compression ratio: {ratio:.1f}%")

    if skipped > 0:
        logger.warning(f"⚠️  Skipped {skipped} files")

    if failed:
        logger.error(f"❌ Failed to process {len(failed)} files:")
        for path, error in failed[:10]:
            logger.error(f"  - {path}: {error}")
        if len(failed) > 10:
            logger.error(f"  ... and {len(failed) - 10} more errors")
    else:
        success_count = total - skipped
        if success_count > 0:
            verb = "compressed" if compress else "decompressed"
            logger.success(f"✅ Successfully {verb} {success_count} files!")
            if remove_original:
                print("   Original files have been removed.")


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Recursively compress or decompress files using Zstandard"
    )
    action_group = parser.add_mutually_exclusive_group(required=False)
    action_group.add_argument(
        "-c", "--compress", action="store_true", help="Compress files (default)"
    )
    action_group.add_argument(
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
        "--threads",
        type=int,
        default=4,
        help="Number of threads per compression call (default: 4)",
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory to process (default: current)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep original files (default: remove on success)",
    )
    return parser


def main() -> int:
    """Entry point: parse arguments and run the compression/decompression."""
    parser = build_parser()
    args = parser.parse_args()

    compress: bool = args.compress
    decompress: bool = args.decompress

    if not compress and not decompress:
        compress = True
        print("No action specified, defaulting to compression mode")

    base_dir = Path(args.dir).resolve()
    if not base_dir.exists():
        logger.error(f"Error: Directory '{base_dir}' does not exist")
        return 1
    if not base_dir.is_dir():
        logger.error(f"Error: '{base_dir}' is not a directory")
        return 1

    remove_original = not args.keep

    print(f"Working directory: {base_dir}")
    print(f"Mode: {'Compression' if compress else 'Decompression'}")
    print(f"Threads: {args.threads}")
    if compress:
        print(f"Compression level: {args.level}")
    print(f"Keep original files: {'Yes' if args.keep else 'No'}")
    print("Scanning directory tree...")

    file_generator = walk_files(base_dir, compress)
    process_files(file_generator, compress, args.level, args.threads, remove_original)
    return 0


if __name__ == "__main__":
    sys.exit(main())
