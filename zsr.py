#!/data/data/com.termux/files/home/.local/bin/python
"""
Zstandard Compression Tool - A modern, high-performance file and directory compression utility.

This script provides efficient compression and decompression of files and directories
using Zstandard (zstd) compression algorithm. It features:
- Chunked parallel compression for large files using multiprocessing
- In-memory compression for smaller files
- Directory compression via tar archives
- Automatic space-saving verification
- Progress logging and statistics
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import mmap
import multiprocessing
import shutil
import sys
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final, Tuple

import zstandard as zstd
from dh import fsz

# Constants
CHUNK_SIZE: Final[int] = (
    512 * 1024
)  # 512KB threshold for chunked vs in-memory compression
ZSTD_LEVEL: Final[int] = 22  # Maximum compression level
ZSTD_THREADS: Final[int] = 4  # Threads for zstd internal compression
MAX_WORKERS: Final[int] = 8  # Fixed number of worker processes for parallel compression
CHUNK_COMPRESSION_SIZE: Final[int] = 32768  # 32KB chunk size for parallel compression

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def compress_chunk(data: bytes) -> bytes:
    """
    Compress a single chunk of data using Zstandard compression.

    Args:
        data: The byte chunk to compress

    Returns:
        Compressed byte data
    """
    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL, threads=1)
    return compressor.compress(data)


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    """
    Compress a large file using chunked parallel processing.

    Args:
        in_path: Path to the input file
        out_path: Path where compressed output will be written
        file_size: Size of the input file in bytes

    Returns:
        True if compression was successful, False otherwise
    """
    try:
        chunk_count = (file_size + CHUNK_COMPRESSION_SIZE - 1) // CHUNK_COMPRESSION_SIZE

        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks = (
                mm[
                    i * CHUNK_COMPRESSION_SIZE : min(
                        (i + 1) * CHUNK_COMPRESSION_SIZE, file_size
                    )
                ]
                for i in range(chunk_count)
            )

            # Using ProcessPoolExecutor with fixed 8 workers
            with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(compress_chunk, bytes(chunk)): i
                    for i, chunk in enumerate(chunks)
                }

                results: list[bytes | None] = [None] * chunk_count
                for future in as_completed(futures):
                    idx = futures[future]
                    results[idx] = future.result()

                for compressed_chunk in results:
                    if compressed_chunk:
                        fout.write(compressed_chunk)
                    else:
                        return False
            return True
    except Exception as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def compress_in_memory(infile: Path, outfile: Path) -> bool:
    """
    Compress a file entirely in memory using Zstandard compression.

    Args:
        infile: Path to the input file
        outfile: Path where compressed output will be written

    Returns:
        True if compression was successful, False otherwise
    """
    try:
        data = infile.read_bytes()
        if not data:
            return False

        compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL, threads=ZSTD_THREADS)
        compressed = compressor.compress(data)
        outfile.write_bytes(compressed)
        return True
    except Exception as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_file(path: Path) -> tuple[bool, int, int]:
    """
    Compress a single file and remove the original if space is saved.

    Args:
        path: Path to the file to compress

    Returns:
        Tuple containing (success_status, original_size, compressed_size)
    """
    out_path = path.with_suffix(path.suffix + ".zst")
    if out_path.exists():
        print(f"Skipping {path.name} - output already exists")
        return (False, 0, 0)

    try:
        original_size = path.stat().st_size
        if original_size == 0:
            return (False, 0, 0)

        # Choose compression method based on file size
        if original_size < CHUNK_SIZE:
            success = compress_in_memory(path, out_path)
        else:
            success = compress_chunked(path, out_path, original_size)

        if success and out_path.exists():
            compressed_size = out_path.stat().st_size
            if compressed_size < original_size:
                path.unlink()
                reduction = (original_size - compressed_size) / original_size * 100
                print(
                    f"  ✓ {path.name}: {reduction:.1f}% saved ({fsz(original_size)} → {fsz(compressed_size)})"
                )
                return (True, original_size, compressed_size)
            else:
                print(f"  ✗ {path.name}: No space saved, removing compressed file")
                out_path.unlink()
                return (False, 0, 0)
    except Exception as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")

    return (False, 0, 0)


def decompress_file(path: Path) -> bool:
    """
    Decompress a single .zst file and remove the compressed version.

    Args:
        path: Path to the .zst file to decompress

    Returns:
        True if decompression was successful, False otherwise
    """
    if path.suffix != ".zst":
        return False

    out_path = path.with_suffix("")
    try:
        dctx = zstd.ZstdDecompressor()
        with path.open("rb") as f_in, out_path.open("wb") as f_out:
            dctx.copy_stream(f_in, f_out)

        original_size = path.stat().st_size
        decompressed_size = out_path.stat().st_size
        print(
            f"  ✓ Decompressed {path.name}: {fsz(original_size)} → {fsz(decompressed_size)}"
        )
        path.unlink()
        return True
    except Exception as e:
        logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
        return False


def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    """
    Create a tar archive of a directory.

    Args:
        source_dir: Directory to archive
        output_path: Path where the tar archive will be created

    Returns:
        True if archive creation was successful, False otherwise
    """
    try:
        with tarfile.open(output_path, "w") as tar:
            tar.add(source_dir, arcname=source_dir.name)
        return True
    except Exception as e:
        logger.error(f"  Failed to create tar archive: {e}")
        return False


async def compress_folder_async(folder_path: Path, output_base_name: str) -> bool:
    """
    Compress a folder by creating and compressing a tar archive.

    Args:
        folder_path: Path to the folder to compress
        output_base_name: Base name for output files

    Returns:
        True if compression was successful, False otherwise
    """
    loop = asyncio.get_running_loop()
    tar_path = Path(f"{output_base_name}.tar")
    zst_path = Path(f"{output_base_name}.tar.zst")

    try:
        print(f"  Creating tar archive for {folder_path.name}...")
        success = await loop.run_in_executor(
            None, create_tar_archive, folder_path, tar_path
        )
        if not success or not tar_path.exists():
            return False

        print("  Compressing tar archive with Zstandard...")
        tar_size = tar_path.stat().st_size

        if tar_size < CHUNK_SIZE:
            success = await loop.run_in_executor(
                None, compress_in_memory, tar_path, zst_path
            )
        else:
            success = await loop.run_in_executor(
                None, compress_chunked, tar_path, zst_path, tar_size
            )

        if success and zst_path.exists():
            zst_size = zst_path.stat().st_size
            if zst_size < tar_size:
                tar_path.unlink()
                reduction = (tar_size - zst_size) / tar_size * 100
                print(
                    f"  ✓ Compressed archive: {reduction:.1f}% saved ({fsz(tar_size)} → {fsz(zst_size)})"
                )
                await loop.run_in_executor(None, shutil.rmtree, folder_path)
                return True
            else:
                print("  ✗ Archive compression didn't save space")
                zst_path.unlink()
        return False
    except Exception as e:
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        return False


async def process_compress() -> None:
    """
    Process compression of all files and directories in the current working directory.
    """
    cwd = Path.cwd()
    print(f"\n🔧 Zstandard Compression Settings (Level {ZSTD_LEVEL})")

    # Compress directories
    dirs = [p for p in cwd.iterdir() if p.is_dir() and p.name not in SKIP_DIRS]
    if dirs:
        print(f"\n📁 Compressing {len(dirs)} directories...")
        for d in sorted(dirs):
            await compress_folder_async(d, str(d))

    # Compress individual files
    files = [
        p
        for p in cwd.iterdir()
        if p.is_file()
        and (p.suffix not in (".zst", ".tar", ".gz", ".zip"))
        and (p.stat().st_size >= 1024)
    ]

    if files:
        print(f"\n📄 Compressing {len(files)} files...")
        total_orig = 0
        total_comp = 0
        successful = 0

        for i, f in enumerate(sorted(files), 1):
            print(f"[{i}/{len(files)}] {f.name}")
            success, o_sz, c_sz = compress_file(f)
            if success:
                successful += 1
                total_orig += o_sz
                total_comp += c_sz

        if successful > 0:
            saved = total_orig - total_comp
            print(
                f"\n{'=' * 40}\n✅ Compressed {successful} files\n📊 Saved "
                f"{fsz(saved)} ({saved / total_orig * 100:.1f}%)\n{'=' * 40}"
            )


async def process_decompress() -> None:
    """
    Process decompression of all compressed files and archives in the current working directory.
    """
    cwd = Path.cwd()

    # Decompress tar archives
    archives = list(cwd.glob("*.tar.zst"))
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for arch in sorted(archives):
            print(f"  Processing {arch.name}...")
            tar_path = arch.with_suffix("")
            try:
                dctx = zstd.ZstdDecompressor()
                with arch.open("rb") as f_in, tar_path.open("wb") as f_out:
                    dctx.copy_stream(f_in, f_out)

                extract_dir = arch.name.removesuffix(".tar.zst")
                with tarfile.open(tar_path, "r") as tar:
                    tar.extractall(path=Path(extract_dir))

                tar_path.unlink()
                arch.unlink()
                print(f"  ✓ Extracted to {extract_dir}/")
            except Exception as e:
                logger.error(f"  ✗ Failed to decompress {arch.name}: {e}")

    # Decompress individual files
    zst_files = [p for p in cwd.glob("*.zst") if not p.name.endswith(".tar.zst")]
    if zst_files:
        print(f"\n📄 Decompressing {len(zst_files)} files...")
        for f in sorted(zst_files):
            decompress_file(f)


def main() -> None:
    """
    Main entry point for the compression tool.
    Parses command-line arguments and executes compression or decompression.
    """
    parser = argparse.ArgumentParser(description="Modern Zstandard compression tool")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", default=True)
    group.add_argument("-d", "--decompress", action="store_true")
    args = parser.parse_args()

    try:
        asyncio.run(process_decompress() if args.decompress else process_compress())
    except KeyboardInterrupt:
        print("\nInterrupted by user")


if __name__ == "__main__":
    raise SystemExit(main())
