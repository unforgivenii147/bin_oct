#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively compress or decompress files using Zstandard.

Prompt: Write a Python CLI tool that walks a directory tree and compresses
compressible files to `.zst` using zstandard, or decompresses `.zst` files
back to their originals. Skip already-compressed media/binaries, archives,
symlinks, and excluded directories (VCS, caches, egg-info/dist-info, editable
packages). Use multiprocessing.Pool with 8 fixed workers via apply_async.
Use loguru for logging, pathlib for paths, argparse for CLI flags
(-c/--compress, -d/--decompress, --level 1-22, --dir, --keep), and report
aggregate space savings.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections.abc import Iterator
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path

import zstandard as zstd
from dh import fsz
from loguru import logger

SKIP_EXTENSIONS_COMPRESS: frozenset[str] = frozenset(
    {
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
        ".dat",
        ".npz",
        ".onnx",
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
        ".dylib",
        ".bin",
        ".iso",
        ".img",
        ".deb",
        ".rpm",
        ".pkg",
        ".msi",
    }
)

MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
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
)

VALID_DECOMPRESS_EXTENSIONS: frozenset[str] = frozenset({".zst"})

SKIP_DIRS: frozenset[str] = frozenset(
    {
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
)

SKIP_DIR_PATTERNS: list[str] = ["*.egg-info", "*.dist-info"]

POOL_WORKERS: int = 8
READ_CHUNK: int = 131072


class SpaceStats:
    """Accumulates original and compressed byte totals across processes.

    Fields are only meaningful in the parent process; worker results are
    aggregated back in the parent.
    """

    def __init__(self) -> None:
        self.original_size: int = 0
        self.compressed_size: int = 0

    def add(self, original: int, compressed: int) -> None:
        """Add a single file's original and compressed sizes to the totals."""
        self.original_size += original
        self.compressed_size += compressed

    def get_savings(self) -> tuple[int, float, float]:
        """Return (saved_bytes, ratio_pct, percent_saved)."""
        if self.original_size == 0:
            return 0, 0.0, 0.0
        saved = self.original_size - self.compressed_size
        ratio = self.compressed_size / self.original_size * 100.0
        percent_saved = saved / self.original_size * 100.0
        return saved, ratio, percent_saved


def should_skip_directory(dir_name: str) -> bool:
    """Return True if the directory name matches the skip list or patterns."""
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


def is_editable_package_dir(root_path: Path) -> bool:
    """Return True if root_path contains an editable-package marker."""
    try:
        for item in root_path.iterdir():
            if item.is_dir() and item.name.endswith(".egg-info"):
                egg_info_path = item / "SOURCES.txt"
                if egg_info_path.exists():
                    return True
                direct_url = item / "direct_url.json"
                if direct_url.exists():
                    try:
                        with direct_url.open() as f:
                            data: dict[str, object] = json.load(f)
                        dir_info = data.get("dir_info", {})
                        if isinstance(dir_info, dict) and dir_info.get(
                            "editable", False
                        ):
                            return True
                    except (json.JSONDecodeError, OSError):
                        pass
        return False
    except (PermissionError, OSError):
        return False


def iter_files(base_dir: Path, compress: bool) -> Iterator[Path]:
    """Yield files under base_dir eligible for the requested operation."""
    skipped_symlinks = 0
    skipped_extensions = 0
    skipped_editable = 0
    skipped_dirs = 0
    skipped_media = 0

    def accept_file(path: Path) -> bool:
        nonlocal skipped_extensions, skipped_media
        path_str = str(path)
        if ".egg-info" in path_str or ".dist-info" in path_str:
            skipped_extensions += 1
            return False
        if compress:
            suf = path.suffix.lower()
            if suf in SKIP_EXTENSIONS_COMPRESS:
                skipped_extensions += 1
                if suf in MEDIA_EXTENSIONS:
                    skipped_media += 1
                return False
            return True
        if path.name.endswith(".tar.zst"):
            skipped_extensions += 1
            return False
        if path.suffix not in VALID_DECOMPRESS_EXTENSIONS:
            skipped_extensions += 1
            return False
        return True

    for root, dirs, file_names in base_dir.walk():
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
        for file_name in file_names:
            path = root_path / file_name
            if path.is_symlink():
                skipped_symlinks += 1
                continue
            if accept_file(path):
                yield path

    if skipped_symlinks > 0:
        logger.warning("Skipped {} symlinks", skipped_symlinks)
    if skipped_media > 0:
        print("Skipped {} media/binary files (already compressed)", skipped_media)
    if skipped_extensions > 0:
        print("Skipped {} files with unwanted extensions", skipped_extensions)
    if skipped_editable > 0:
        print("Skipped {} editable package directories", skipped_editable)
    if skipped_dirs > 0:
        print("Skipped {} excluded directories", skipped_dirs)


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int,
    remove_original: bool,
) -> tuple[bool, Path, Path | str, int, int]:
    """Compress a single file to Zstandard. Returns a result tuple."""
    try:
        original_size = input_path.stat().st_size
        compressor = zstd.ZstdCompressor(level=level, threads=1)
        with input_path.open("rb") as infile, output_path.open("wb") as outfile:
            reader = compressor.stream_reader(infile)
            while True:
                chunk = reader.read(READ_CHUNK)
                if not chunk:
                    break
                outfile.write(chunk)
        compressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return True, input_path, output_path, original_size, compressed_size
    except Exception as e:
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        return False, input_path, str(e), 0, 0


def decompress_file(
    input_path: Path,
    output_path: Path,
    remove_original: bool,
) -> tuple[bool, Path, Path | str, int, int]:
    """Decompress a single .zst file. Returns a result tuple."""
    try:
        compressed_size = input_path.stat().st_size
        decompressor = zstd.ZstdDecompressor()
        with input_path.open("rb") as infile, output_path.open("wb") as outfile:
            reader = decompressor.stream_reader(infile)
            while True:
                chunk = reader.read(READ_CHUNK)
                if not chunk:
                    break
                outfile.write(chunk)
        decompressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return True, input_path, output_path, decompressed_size, compressed_size
    except Exception as e:
        try:
            if output_path.exists():
                output_path.unlink()
        except OSError:
            pass
        return False, input_path, str(e), 0, 0


def _output_path_for(p: Path, compress: bool) -> Path:
    """Return the output path corresponding to input path p."""
    if compress:
        return p.with_suffix(p.suffix + ".zst")
    return p.with_suffix("")


def process_stream(
    base_dir: Path,
    compress: bool,
    level: int,
    remove_original: bool,
) -> None:
    """Walk base_dir and compress or decompress eligible files in parallel."""
    print(
        "{} files (streaming)...",
        "Compressing" if compress else "Decompressing",
    )
    print("Remove original files: {}", "Yes" if remove_original else "No")

    stats = SpaceStats()
    total_submitted = 0
    completed = 0
    skipped = 0
    failed: list[tuple[Path, str]] = []

    # First pass: build the list of tasks (so we know the total up-front).
    tasks: list[tuple[Path, Path]] = []
    for path in iter_files(base_dir, compress):
        op_out = _output_path_for(path, compress)
        if op_out.exists():
            skipped += 1
            completed += 1
            continue
        tasks.append((path, op_out))

    total_submitted = len(tasks)
    grand_total = total_submitted + skipped

    def _report_progress() -> None:
        progress = int(completed / max(1, grand_total) * 40)
        bar = "█" * progress + "░" * (50 - progress)
        logger.opt(colors=False).info(
            "\rProgress: [{}] {}/{} files", bar, completed, grand_total
        )

    if total_submitted == 0:
        logger.warning("No files were processed.")
        return

    with Pool(processes=POOL_WORKERS) as pool:
        async_results: list[AsyncResult[tuple[bool, Path, Path | str, int, int]]] = []
        for path, op_out in tasks:
            if compress:
                ar = pool.apply_async(
                    compress_file,
                    (path, op_out, level, remove_original),
                )
            else:
                ar = pool.apply_async(
                    decompress_file,
                    (path, op_out, remove_original),
                )
            async_results.append(ar)

        for ar in async_results:
            result = ar.get()
            completed += 1
            _report_progress()
            ok, path, info, orig, comp = result
            if ok:
                stats.add(orig, comp)
            else:
                failed.append((path, str(info)))
        print()

    if compress and (stats.original_size > 0 or stats.compressed_size > 0):
        saved, ratio, percent_saved = stats.get_savings()
        print("📊 Compression Statistics:")
        print("   Original size:  {}", fsz(stats.original_size))
        print("   Compressed size: {}", fsz(stats.compressed_size))
        print("   Space saved:    {} ({:.1f}%)", fsz(saved), percent_saved)
        print("   Compression ratio: {:.1f}%", ratio)

    if skipped > 0:
        logger.warning("Skipped {} files (already exist or invalid format)", skipped)

    if failed:
        logger.error("❌ Failed to process {} files:", len(failed))
        for path, error in failed[:200]:
            logger.error("  - {}: {}", path, error)
        if len(failed) > 200:
            logger.error("  ... and {} more", len(failed) - 200)
    else:
        success_count = total_submitted
        if success_count > 0:
            logger.success(
                "✅ Successfully {} {} files!",
                "compressed" if compress else "decompressed",
                success_count,
            )
            if remove_original:
                print("   Original files have been removed.")
        else:
            logger.warning("No files were processed.")


def main() -> int:
    """CLI entry point."""
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
        "--dir",
        type=str,
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "--keep",
        default=False,
        action="store_true",
        help="Keep original files (default: remove on success)",
    )
    args = parser.parse_args()

    if not args.compress and not args.decompress:
        args.compress = True
        print("No action specified, defaulting to compression mode")

    base_dir = Path(args.dir).resolve()
    if not base_dir.exists():
        logger.error("Directory '{}' does not exist", base_dir)
        return 1
    if not base_dir.is_dir():
        logger.error("'{}' is not a directory", base_dir)
        return 1

    remove_original = not args.keep

    print("Working directory: {}", base_dir)
    print("Mode: {}", "Compression" if args.compress else "Decompression")
    print("Pool workers: {}", POOL_WORKERS)
    if args.compress:
        print("Compression level: {}", args.level)
    print("Keep original files: {}", "Yes" if args.keep else "No")
    print("Scanning directory tree...")

    process_stream(base_dir, args.compress, args.level, remove_original)
    return 0


if __name__ == "__main__":
    sys.exit(main())
