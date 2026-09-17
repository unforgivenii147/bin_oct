#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that recursively compresses (using lzma_mt with multithreading) or decompresses .xz files in a directory tree. Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers. Use pathlib for all path handling, loguru for logging, full type hints, argparse CLI with -c/--compress, -d/--decompress, --preset (0-9), --threads, and --keep-orig flags plus an optional directory argument. Skip common exclude directories (.git, __pycache__, .venv, venv, .env, node_modules) and skip already-archived files when compressing.
"""

from __future__ import annotations

import argparse
import textwrap
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
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
    ".z",
    ".lz",
    ".lzma",
    ".xza",
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


def should_exclude(path: Path) -> bool:
    """Return True if any part of the path is in EXCLUDE_DIRS."""
    return any(part in EXCLUDE_DIRS for part in path.parts)


def get_files_to_process(root_dir: Path, compress: bool) -> list[Path]:
    """Return a sorted list of files under root_dir eligible for processing."""
    files: list[Path] = []
    if compress:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file):
                if file.suffix.lower() not in ARCHIVE_EXTENSIONS:
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
    path: Path,
    preset: int = 9,
    threads: int = 4,
    remove_orig: bool = True,
) -> tuple[Path, bool, str]:
    """Compress a single file with lzma_mt, optionally removing the original."""
    try:
        with open(path, "rb") as f:
            data: bytes = f.read()
        compressed: bytes = lzma_mt.compress(data, preset=preset, threads=threads)
        output_path: Path = path.parent / (path.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        if remove_orig:
            path.unlink()
        return path, True, f"Compressed to {output_path.name}"
    except Exception as e:
        return path, False, f"Error: {e!s}"


def decompress_file(
    path: Path,
    remove_orig: bool = True,
) -> tuple[Path, bool, str]:
    """Decompress a single .xz file, optionally removing the original."""
    try:
        if path.suffix.lower() != ".xz":
            return path, False, "Error: Not an .xz file"
        with open(path, "rb") as f:
            data: bytes = f.read()
        decompressed: bytes = lzma_mt.decompress(data)
        output_path: Path = path.parent / path.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        if remove_orig:
            path.unlink()
        return path, True, f"Decompressed to {output_path.name}"
    except Exception as e:
        return path, False, f"Error: {e!s}"


def _process_files_impl(
    root_dir: Path,
    compress: bool,
    preset: int,
    threads: int,
    remove_orig: bool,
) -> None:
    """Internal worker function performing the pool-based processing."""
    files: list[Path] = get_files_to_process(root_dir, compress)
    if not files:
        action: str = "compress" if compress else "decompress"
        print(f"No files found to {action}")
        return

    action = "Compressing" if compress else "Decompressing"
    print(f"{action} {len(files)} files with {NUM_WORKERS} workers...")
    print(f"Preset: {preset}, Threads: {threads}")

    total_success: int = 0
    total_failed: int = 0
    total: int = len(files)

    with Pool(processes=NUM_WORKERS) as pool:
        results: list[AsyncResult[tuple[Path, bool, str]]] = []
        if compress:
            for file in files:
                results.append(
                    pool.apply_async(
                        compress_file, (file, preset, threads, remove_orig)
                    )
                )
        else:
            for file in files:
                results.append(pool.apply_async(decompress_file, (file, remove_orig)))

        completed: int = 0
        for result in results:
            path, success, message = result.get()
            completed += 1
            pct: float = completed / total * 40
            print(f"[{pct:5.1f}%] {completed}/{total}")
            if success:
                total_success += 1
                status: str = "✓"
            else:
                total_failed += 1
                status = "✗"
            rel_path: Path = path.relative_to(root_dir)
            print(f"{status} {rel_path}: {message}")

    print("─" * 40)
    print(f"Total successful: {total_success}")
    print(f"Total failed: {total_failed}")


def process_files(
    root_dir: Path,
    compress: bool,
    preset: int,
    threads: int,
    remove_orig: bool = True,
) -> None:
    """Process all eligible files under root_dir in parallel."""
    _process_files_impl(root_dir, compress, preset, threads, remove_orig)


def main() -> int:
    """Parse arguments and dispatch to process_files."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Compress or decompress files using lzma_mt with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python compress_files.py
              python compress_files.py -c --preset 6 --threads 8
              python compress_files.py -d /path/to/files
              python compress_files.py -c /path/to/files
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
    args: argparse.Namespace = parser.parse_args()

    if args.compress and args.decompress:
        logger.error("Cannot specify both -c and -d")
        return 1

    compress_mode: bool = args.compress or not args.decompress
    root_dir: Path = Path(args.directory).resolve()
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
