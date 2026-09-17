#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursively compress or decompress files using lzma_mt with parallel processing.

This script provides a CLI tool that walks a directory tree, filters out
archives/media/excluded directories, and either compresses eligible files to
`.xz` using `lzma_mt` or decompresses existing `.xz` files back to their
original form. It uses a fixed multiprocessing pool of 8 workers, logs via
loguru, and uses pathlib throughout.
"""

from __future__ import annotations

import argparse
import textwrap
from multiprocessing import Pool
from pathlib import Path
from typing import Final

import lzma_mt
from loguru import logger

ARCHIVE_EXTENSIONS: Final[set[str]] = {
    ".zip",
    ".br",
    ".xz",
    ".gz",
    ".bz2",
    ".bz3",
    ".zst",
    ".7z",
    ".lz4",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".Z",
    ".lz",
    ".lzma",
    ".xza",
}

MEDIA_EXTENSIONS: Final[set[str]] = {
    ".mkv",
    ".mp4",
    ".webm",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".mp3",
    ".aac",
    ".flac",
    ".wav",
    ".m4a",
    ".opus",
    ".ogg",
    ".wma",
    ".alac",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".tiff",
    ".ico",
    ".heic",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".iso",
    ".img",
}

EXCLUDE_DIRS: Final[set[str]] = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "node_modules",
}

NUM_WORKERS: Final[int] = 8

Result = tuple[Path, bool, str, int, int]


def should_exclude(path: Path) -> bool:
    """Return True if any path component is in EXCLUDE_DIRS."""
    return any(part in EXCLUDE_DIRS for part in path.parts)


def is_media_file(path: Path) -> bool:
    """Return True if the file's suffix is in MEDIA_EXTENSIONS."""
    return path.suffix.lower() in MEDIA_EXTENSIONS


def get_files_to_process(root_dir: Path, compress: bool) -> list[Path]:
    """Collect files under root_dir eligible for compression or decompression."""
    files: list[Path] = []
    if compress:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file):
                suffix = file.suffix.lower()
                if suffix not in ARCHIVE_EXTENSIONS and not is_media_file(file):
                    files.append(file)
    else:
        for file in root_dir.rglob("*"):
            if (
                file.is_file()
                and not should_exclude(file)
                and file.suffix.lower() == ".xz"
            ):
                files.append(file)
    return sorted(files)


def compress_file(
    args: tuple[Path, int, int, bool],
) -> Result:
    """Compress a single file to .xz, optionally removing the original."""
    path, preset, threads, remove_orig = args
    try:
        with open(path, "rb") as f:
            data = f.read()
        original_size = len(data)
        compressed = lzma_mt.compress(data, preset=preset, threads=threads)
        output_path = path.parent / (path.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        space_freed = 0
        if remove_orig:
            path.unlink()
            space_freed = original_size
        return (
            path,
            True,
            f"Compressed to {output_path.name}",
            original_size,
            space_freed,
        )
    except Exception as e:
        return path, False, f"Error: {e!s}", 0, 0


def decompress_file(args: tuple[Path, bool]) -> Result:
    """Decompress a single .xz file, optionally removing the original."""
    path, remove_orig = args
    try:
        if path.suffix.lower() != ".xz":
            return path, False, "Error: Not an .xz file", 0, 0
        with open(path, "rb") as f:
            data = f.read()
        compressed_size = len(data)
        decompressed = lzma_mt.decompress(data)
        output_path = path.parent / path.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        space_freed = 0
        if remove_orig:
            path.unlink()
            space_freed = compressed_size
        return (
            path,
            True,
            f"Decompressed to {output_path.name}",
            compressed_size,
            space_freed,
        )
    except Exception as e:
        return path, False, f"Error: {e!s}", 0, 0


def format_bytes(bytes_val: int) -> str:
    """Format a byte count as a human-readable string."""
    value: float = float(bytes_val)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def process_files(
    root_dir: Path,
    compress: bool,
    preset: int,
    threads: int,
    remove_orig: bool = True,
) -> None:
    """Process all eligible files using a fixed pool of 8 workers."""
    files = get_files_to_process(root_dir, compress)
    if not files:
        action = "compress" if compress else "decompress"
        print(f"No files found to {action}")
        return

    action = "Compressing" if compress else "Decompressing"
    print(f"{action} {len(files)} files with {NUM_WORKERS} workers...")
    print(f"Preset: {preset}, Threads: {threads}")

    total_success = 0
    total_failed = 0
    total_space_freed = 0
    total_original_size = 0
    total = len(files)
    completed = 0

    with Pool(processes=NUM_WORKERS) as pool:
        if compress:
            async_results = [
                pool.apply_async(compress_file, ((file, preset, threads, remove_orig),))
                for file in files
            ]
        else:
            async_results = [
                pool.apply_async(decompress_file, ((file, remove_orig),))
                for file in files
            ]

        for async_result in async_results:
            path, success, message, orig_size, space_freed = async_result.get()
            completed += 1
            pct = completed / total * 40
            print(f"[{pct:5.1f}%] {completed}/{total}")
            if success:
                total_success += 1
                status = "✓"
                total_space_freed += space_freed
                if compress:
                    total_original_size += orig_size
            else:
                total_failed += 1
                status = "✗"
            rel_path = path.relative_to(root_dir)
            print(f"{status} {rel_path}: {message}")

    print(f"{'─' * 40}")
    print(f"Total successful: {total_success}")
    print(f"Total failed: {total_failed}")
    if compress and total_original_size > 0:
        print(f"Total original size: {format_bytes(total_original_size)}")
        if total_space_freed > 0:
            print(f"Disk space freed: {format_bytes(total_space_freed)}")


def main() -> int:
    """Parse CLI arguments and run the compression/decompression workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Recursively compress or decompress files using lzma_mt "
            "with parallel processing"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python compress_files.py
              python compress_files.py -c --preset 6 --threads 8
              python compress_files.py -d /path/to/files
              python compress_files.py -c /path/to/files
              python compress_files.py --keep-orig
            Excluded by default:
              - Directories: .git, __pycache__, .venv, venv, node_modules
              - Archives: .zip, .br, .xz, .gz, .bz2, .bz3, .zst, .7z, .lz4, etc.
              - Media: .mp4, .mkv, .mp3, .jpg, .png, .pdf, .exe, etc.
            """),
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no -d specified)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .xz files",
    )
    parser.add_argument(
        "--preset",
        type=int,
        default=9,
        choices=range(10),
        help="Compression preset 0-9 (default: 9)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Threads per compression job (default: 4)",
    )
    parser.add_argument(
        "--keep-orig",
        action="store_true",
        help="Keep original files after compression/decompression",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    args = parser.parse_args()

    if args.compress and args.decompress:
        logger.error("Cannot specify both -c and -d")
        return 1

    compress_mode = args.compress or not args.decompress
    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        logger.error(f"{root_dir} is not a directory")
        return 1

    process_files(
        root_dir,
        compress=compress_mode,
        preset=args.preset,
        threads=args.threads,
        remove_orig=not args.keep_orig,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
