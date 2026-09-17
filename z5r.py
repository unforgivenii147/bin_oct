#!/data/data/com.termux/files/home/.local/bin/python
"""
Optimized Folder Zstd Archiver.

This script provides efficient parallel compression and decompression of folders
using Zstandard compression. It supports multi-threaded compression, configurable
compression levels, and parallel processing of multiple folders.

Features:
- Parallel compression/decompression using multiprocessing
- Zstandard compression with configurable levels
- Rich progress bar support (optional)
- Automatic cleanup of temporary files
- Skip lists for common non-essential directories
"""

import argparse
import multiprocessing as mp
import tarfile
import time
from dataclasses import dataclass
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, List

import zstandard as zstd
from dh import fsz, gsz
from loguru import logger

DEFAULT_SKIP_DIRS: Final[set[str]] = {
    "zstandard",
    "0",
    "compressed",
    "faprint",
    "packaging",
    "joblib",
    "loguru",
    "setuptools",
    "pip",
    "wheel",
    ".git",
    "dist",
    "build",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    RICH_AVAILABLE: Final[bool] = True
except ImportError:
    RICH_AVAILABLE: Final[bool] = False


def remove_tree(path: Path) -> None:
    """
    Recursively remove a directory tree or file.

    Args:
        path: Path to the file or directory to remove.
    """
    if not path.exists():
        return
    if path.is_file() or path.is_symlink():
        path.unlink()
    else:
        for child in path.iterdir():
            remove_tree(child)
        path.rmdir()


def stream_copy(
    src_file: object | zstd.ZstdDecompressionReader,
    dst_file: object | zstd.ZstdCompressionWriter,
    chunk_size: int = 1024 * 1024,
) -> None:
    """
    Copy data from source to destination in chunks.

    Args:
        src_file: Source file object to read from.
        dst_file: Destination file object to write to.
        chunk_size: Size of each read/write chunk in bytes.
    """
    while True:
        chunk = src_file.read(chunk_size)
        if not chunk:
            break
        dst_file.write(chunk)


@dataclass(slots=True)
class FolderResult:
    """
    Represents the result of a compression or decompression operation.

    Attributes:
        name: Name of the folder/archive processed.
        original_size: Original size in bytes before operation.
        compressed_size: Size in bytes after compression (or before decompression).
        success: Whether the operation succeeded.
        error: Error message if operation failed.
        duration: Time taken for the operation in seconds.
    """

    name: str
    original_size: int = 0
    compressed_size: int = 0
    success: bool = False
    error: str | None = None
    duration: float = 0.0

    @property
    def saved_bytes(self) -> int:
        """
        Calculate the number of bytes saved by compression.

        Returns:
            Number of bytes saved (original_size - compressed_size).
        """
        return max(0, self.original_size - self.compressed_size)


def compress_folder_task(
    folder_path: Path, output_dir: Path, level: int = 3, threads: int = 0
) -> FolderResult:
    """
    Compress a folder to a .tar.zst archive.

    Args:
        folder_path: Path to the folder to compress.
        output_dir: Directory to save the compressed archive.
        level: Zstandard compression level (1-22).
        threads: Number of threads for Zstandard compression (0 = auto).

    Returns:
        FolderResult containing compression results.
    """
    start_time = time.perf_counter()
    folder_name = folder_path.name
    zst_path = output_dir / f"{folder_name}.tar.zst"
    temp_tar = output_dir / f".tmp_{folder_name}.tar"
    try:
        orig_size = gsz(folder_path)
        print(f"Compressing {folder_name} (size: {fsz(orig_size)})")

        with tarfile.open(temp_tar, "w") as tar:
            tar.add(folder_path, arcname=folder_name)

        cctx = zstd.ZstdCompressor(level=level, threads=threads)
        with (
            temp_tar.open("rb") as f_in,
            zst_path.open("wb") as f_out,
            cctx.stream_writer(f_out) as compressor,
        ):
            stream_copy(f_in, compressor)

        comp_size = zst_path.stat().st_size
        temp_tar.unlink()
        remove_tree(folder_path)

        print(f"Compressed {folder_name}: {fsz(orig_size)} -> {fsz(comp_size)}")

        return FolderResult(
            name=folder_name,
            original_size=orig_size,
            compressed_size=comp_size,
            success=True,
            duration=time.perf_counter() - start_time,
        )
    except Exception as e:
        logger.error(f"Failed to compress {folder_name}: {e!s}")
        if temp_tar.exists():
            temp_tar.unlink()
        if zst_path.exists():
            zst_path.unlink()
        return FolderResult(name=folder_name, success=False, error=str(e))


def decompress_folder_task(zst_path: Path, output_dir: Path) -> FolderResult:
    """
    Decompress a .tar.zst archive to a folder.

    Args:
        zst_path: Path to the compressed archive.
        output_dir: Directory to extract the folder to.

    Returns:
        FolderResult containing decompression results.
    """
    start_time = time.perf_counter()
    folder_name = zst_path.name.removesuffix(".tar.zst")
    temp_tar = output_dir / f".tmp_{folder_name}.tar"
    try:
        comp_size = zst_path.stat().st_size
        print(f"Decompressing {folder_name} (size: {fsz(comp_size)})")

        dctx = zstd.ZstdDecompressor()
        with (
            zst_path.open("rb") as f_in,
            temp_tar.open("wb") as f_out,
            dctx.stream_reader(f_in) as decompressor,
        ):
            stream_copy(decompressor, f_out)

        with tarfile.open(temp_tar, "r") as tar:
            tar.extractall(output_dir, filter="data")

        temp_tar.unlink()
        zst_path.unlink()
        extracted_size = gsz(output_dir / folder_name)

        print(f"Decompressed {folder_name}: {fsz(comp_size)} -> {fsz(extracted_size)}")

        return FolderResult(
            name=folder_name,
            original_size=extracted_size,
            compressed_size=comp_size,
            success=True,
            duration=time.perf_counter() - start_time,
        )
    except Exception as e:
        logger.error(f"Failed to decompress {folder_name}: {e!s}")
        if temp_tar.exists():
            temp_tar.unlink()
        return FolderResult(name=folder_name, success=False, error=str(e))


def process_targets_with_progress(
    targets: list[Path], mode: str, root: Path, workers: int, level: int
) -> list[FolderResult]:
    """
    Process targets with rich progress bar display.

    Args:
        targets: List of paths to process.
        mode: Either "Compressing" or "Decompressing".
        root: Root directory for operations.
        workers: Number of parallel workers.
        level: Compression level (only for compression).

    Returns:
        List of FolderResult objects.
    """
    console = Console()
    results: list[FolderResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"{mode}...", total=len(targets))

        with Pool(processes=min(workers, 8)) as pool:
            async_results: list[AsyncResult] = []

            if mode == "Decompressing":
                for t in targets:
                    async_results.append(
                        pool.apply_async(decompress_folder_task, (t, root))
                    )
            else:
                for t in targets:
                    async_results.append(
                        pool.apply_async(compress_folder_task, (t, root, level))
                    )

            completed = 0
            while completed < len(async_results):
                for i, ar in enumerate(async_results):
                    if ar.ready() and ar not in [r for r in results]:
                        try:
                            res = ar.get()
                            results.append(res)
                            completed += 1
                            progress.advance(task)
                            if not res.success:
                                console.print(
                                    f"[red]Error on {res.name}: {res.error}[/red]"
                                )
                        except Exception as e:
                            console.print(f"[red]Worker error: {e!s}[/red]")
                            completed += 1
                            progress.advance(task)
                time.sleep(0.1)

    return results


def process_targets_without_progress(
    targets: list[Path], mode: str, root: Path, workers: int, level: int
) -> list[FolderResult]:
    """
    Process targets without rich progress bar display.

    Args:
        targets: List of paths to process.
        mode: Either "Compressing" or "Decompressing".
        root: Root directory for operations.
        workers: Number of parallel workers.
        level: Compression level (only for compression).

    Returns:
        List of FolderResult objects.
    """
    results: list[FolderResult] = []

    with Pool(processes=min(workers, 8)) as pool:
        async_results: list[AsyncResult] = []

        if mode == "Decompressing":
            for t in targets:
                async_results.append(
                    pool.apply_async(decompress_folder_task, (t, root))
                )
        else:
            for t in targets:
                async_results.append(
                    pool.apply_async(compress_folder_task, (t, root, level))
                )

        completed = 0
        while completed < len(async_results):
            for i, ar in enumerate(async_results):
                if ar.ready():
                    try:
                        res = ar.get()
                        results.append(res)
                        completed += 1
                        print(
                            f"[{completed}/{len(targets)}] {res.name} - {('OK' if res.success else 'FAIL')}"
                        )
                        async_results[i] = None  # Mark as processed
                    except Exception as e:
                        print(f"Worker error: {e!s}")
                        completed += 1
                        async_results[i] = None
            time.sleep(0.1)

    return results


def main() -> int:
    """
    Main entry point for the folder archiver script.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    parser = argparse.ArgumentParser(description="Optimized Folder Zstd Archiver")
    parser.add_argument(
        "-c", "--compress", action="store_true", help="Compress folders"
    )
    parser.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress archives"
    )
    parser.add_argument(
        "-p", "--path", type=Path, default=Path("."), help="Root directory"
    )
    parser.add_argument(
        "-l", "--level", type=int, default=3, help="Compression level (1-22)"
    )
    parser.add_argument(
        "-m", "--min-size", type=float, default=5.0, help="Min folder size in MB"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=min(mp.cpu_count(), 8),
        help="Parallel workers (max 8)",
    )
    args = parser.parse_args()

    # Configure loguru
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")

    root = args.path.resolve()

    if args.decompress:
        targets = list(root.glob("*.tar.zst"))
        mode_name = "Decompressing"
    else:
        targets = [
            d for d in root.iterdir() if d.is_dir() and d.name not in DEFAULT_SKIP_DIRS
        ]
        valid_targets = []
        for d in targets:
            size_mb = gsz(d)
            if size_mb >= args.min_size:
                valid_targets.append(d)
        targets = valid_targets
        mode_name = "Compressing"

    if not targets:
        print("No targets found to process.")
        return 0

    print(f"🚀 {mode_name} {len(targets)} items in {root}...")

    if RICH_AVAILABLE:
        results = process_targets_with_progress(
            targets, mode_name, root, args.workers, args.level
        )
    else:
        results = process_targets_without_progress(
            targets, mode_name, root, args.workers, args.level
        )

    successes = [r for r in results if r.success]
    print(f"\n{'=' * 40}")
    print(f"SUMMARY ({mode_name})")
    print(f"{'=' * 40}")
    print(f"Total: {len(results)}")
    print(f"Success: {len(successes)}")
    print(f"Failed: {len(results) - len(successes)}")

    if successes:
        total_orig = sum(r.original_size for r in successes)
        total_comp = sum(r.compressed_size for r in successes)
        if args.decompress:
            print(f"Extracted size: {fsz(total_orig)}")
        else:
            print(f"Space saved: {fsz(total_orig - total_comp)}")

    print(f"{'=' * 40}")

    return 0 if len(successes) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
