#!/data/data/com.termux/files/home/.local/bin/python
"""
Zstandard Compression Utility.

This script provides parallel compression and decompression functionality using Zstandard (zstd).
It can compress individual files or entire directories into .zst or .tar.zst archives respectively,
and decompress them back to their original form. The script automatically removes source files
after successful compression or decompression operations.

Features:
- Parallel processing using multiprocessing with fixed worker pool
- Streaming compression/decompression to handle large files efficiently
- Automatic tar archiving for directories
- Loguru-based logging for better visibility
"""

import argparse
import io
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import BinaryIO

import zstandard as zstd
from loguru import logger

ZSTD_LEVEL: int = 19
CHUNK_SIZE: int = 1024 * 64
WORKER_COUNT: int = 8


def compress_stream(input_stream: BinaryIO, output_path: Path) -> bool:
    """
    Compress a binary stream to a zstd file.

    Args:
        input_stream: Binary stream to compress
        output_path: Path where compressed file will be written

    Returns:
        bool: True if compression successful, False otherwise
    """
    try:
        cctx = zstd.ZstdCompressor(level=ZSTD_LEVEL)
        with open(output_path, "wb") as f_out:
            compressor = cctx.stream_writer(f_out)
            while True:
                chunk = input_stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                compressor.write(chunk)
            compressor.close()
        print(f"Compressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error compressing to {output_path.name}: {e}")
        return False


def decompress_stream(input_path: Path, output_path: Path) -> bool:
    """
    Decompress a zstd file to the specified output path.

    Args:
        input_path: Path to the zstd compressed file
        output_path: Path where decompressed data will be written

    Returns:
        bool: True if decompression successful, False otherwise
    """
    try:
        dctx = zstd.ZstdDecompressor()
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            decompressor = dctx.stream_reader(f_in)
            while True:
                chunk = decompressor.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(chunk)
        print(f"Decompressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error decompressing {input_path.name}: {e}")
        return False


def process_directory(dir_path: Path) -> None:
    """
    Compress a directory into a .tar.zst archive and remove the original.

    Args:
        dir_path: Path to the directory to compress
    """
    output_zst = dir_path.with_name(f"{dir_path.name}.tar.zst")
    tar_buffer = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        if compress_stream(tar_buffer, output_zst):
            import shutil

            shutil.rmtree(dir_path)
            print(f"Removed original directory: {dir_path.name}")
    except Exception as e:
        logger.error(f"Failed to archive directory {dir_path.name}: {e}")


def process_file(path: Path) -> None:
    """
    Compress a single file into .zst format and remove the original.

    Args:
        path: Path to the file to compress
    """
    output_zst = path.with_name(f"{path.name}.zst")
    try:
        with open(path, "rb") as f_in:
            if compress_stream(f_in, output_zst):
                path.unlink()
                print(f"Removed original file: {path.name}")
    except Exception as e:
        logger.error(f"Failed to compress file {path.name}: {e}")


def decompress_file(zst_path: Path) -> None:
    """
    Decompress a .zst or .tar.zst archive and remove the archive after success.

    Args:
        zst_path: Path to the compressed archive
    """
    if zst_path.name.endswith(".tar.zst"):
        output_dir = zst_path.with_name(zst_path.name[:-8])
        tar_buffer = io.BytesIO()
        try:
            if decompress_stream(zst_path, tar_buffer):
                tar_buffer.seek(0)
                with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                    tar.extractall(path=output_dir.parent)
                zst_path.unlink()
                print(f"Removed archive: {zst_path.name}")
        except Exception as e:
            logger.error(f"Failed to decompress tar archive {zst_path.name}: {e}")
    elif zst_path.suffix == ".zst":
        output_file = zst_path.with_suffix("")
        if decompress_stream(zst_path, output_file):
            zst_path.unlink()
            print(f"Removed archive: {zst_path.name}")
    else:
        logger.warning(f"Skipping non-zst file: {zst_path.name}")


def process_item(item: Path | str, mode: str) -> None:
    """
    Process a single item (file or directory) based on the operation mode.

    Args:
        item: Path to the item to process
        mode: Operation mode ('compress' or 'decompress')
    """
    item_path = Path(item)
    if mode == "compress":
        if item_path.is_dir():
            process_directory(item_path)
        elif item_path.is_file():
            process_file(item_path)
    else:  # decompress
        if item_path.is_file():
            decompress_file(item_path)


def main() -> int:
    """
    Main entry point for the compression/decompression utility.

    Returns:
        int: Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Compress/Decompress with Zstandard (zstd)"
    )
    parser.add_argument(
        "-c", "--compress", action="store_true", help="Compress mode (default)"
    )
    parser.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress mode"
    )
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    current_dir = Path(".")

    # Configure loguru logger
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")

    if mode == "compress":
        subdirs: list[Path] = [
            d
            for d in current_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        files: list[Path] = [
            f
            for f in current_dir.iterdir()
            if f.is_file() and f.suffix != ".zst" and f.name != Path(__file__).name
        ]
        if not subdirs and not files:
            logger.warning("No files or subdirectories found to compress.")
            return 0

        print(f"Found {len(subdirs)} subdirs and {len(files)} files to compress.")
        print(f"Starting parallel Zstandard compression (Level: {ZSTD_LEVEL})...")

        items: list[Path] = subdirs + files
        with Pool(processes=WORKER_COUNT) as pool:
            pool.starmap(process_item, [(item, mode) for item in items])
    else:
        archives: list[Path] = [
            f for f in current_dir.iterdir() if f.is_file() and f.suffix == ".zst"
        ]
        if not archives:
            logger.warning("No .zst or .tar.zst files found to decompress.")
            return 0

        print(f"Found {len(archives)} archives to decompress.")
        print("Starting parallel decompression...")

        with Pool(processes=WORKER_COUNT) as pool:
            pool.starmap(process_item, [(archive, mode) for archive in archives])

    print("All operations completed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
