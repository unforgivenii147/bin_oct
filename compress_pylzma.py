#!/data/data/com.termux/files/home/.local/bin/python
"""
Compress or decompress files recursively using pylzma with multiprocessing.

This script provides a command-line interface to compress files or directories
(optionally tarring subdirectories first) into .7z archives, or decompress
.7z and .tar.7z archives. It uses a fixed multiprocessing pool of 8 workers
for parallel processing and logs progress via loguru.

Usage:
    python script.py [-c|-d] [-t] [-o OUTPUT]

Modes:
    -c, --compress      Compress files (default).
    -d, --decompress    Decompress .7z / .tar.7z files.

Options:
    -t, --tar-subdirs-first   Tar subdirectories before compressing.
    -o, --output OUTPUT       Output directory.
"""

import argparse
import io
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import List

import pylzma
from loguru import logger

# Fixed number of worker processes for the multiprocessing pool.
POOL_WORKERS: int = 8

# Default output directories.
DEFAULT_COMPRESS_OUTPUT: str = "./compressed"
DEFAULT_DECOMPRESS_OUTPUT: str = "./decompressed"


def create_tar_for_directory(dir_path: Path) -> bytes:
    """
    Create an in-memory tar archive of the given directory.

    Args:
        dir_path: Path to the directory to archive.

    Returns:
        The raw bytes of the tar archive.
    """
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        tar.add(str(dir_path), arcname=dir_path.name)
    return tar_buffer.getvalue()


def compress_file(
    path: Path,
    output_dir: Path,
    tar_subdirs_first: bool = False,
) -> str | None:
    """
    Compress a single file or directory into a .7z (or .tar.7z) archive.

    Args:
        path: Path to the file or directory to compress.
        output_dir: Directory where the compressed archive will be written.
        tar_subdirs_first: If True, directories are tarred before compression
            and produce a .tar.7z output.

    Returns:
        A status message string on success, or None if the item was skipped.
        On error, returns an error message string.
    """
    try:
        path = Path(path)
        if path.is_dir():
            if tar_subdirs_first:
                tar_data = create_tar_for_directory(path)
                compressed_data = pylzma.compress(tar_data)
                output_file = output_dir / f"{path.name}.tar.7z"
            else:
                return None
        else:
            with open(path, "rb") as f:
                data = f.read()
            compressed_data = pylzma.compress(data)
            output_file = output_dir / f"{path.name}.7z"

        with open(output_file, "wb") as f:
            f.write(compressed_data)
        return f"Compressed: {path} -> {output_file}"
    except Exception as e:
        return f"Error compressing {path}: {e!s}"


def decompress_file(path: Path, output_dir: Path) -> str:
    """
    Decompress a .7z or .tar.7z archive into the output directory.

    Args:
        path: Path to the compressed archive.
        output_dir: Directory where the decompressed content will be written.

    Returns:
        A status message string describing the result.
    """
    try:
        path = Path(path)
        with open(path, "rb") as f:
            compressed_data = f.read()
        decompressed_data = pylzma.decompress(compressed_data)

        if path.suffixes == [".tar", ".7z"]:
            output_name = path.name.replace(".tar.7z", "")
            tar_buffer = io.BytesIO(decompressed_data)
            with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                tar.extractall(path=str(output_dir))
            return f"Decompressed: {path} -> {output_dir}/{output_name}"
        elif path.suffix == ".7z":
            output_name = path.name.replace(".7z", "")
            output_file = output_dir / output_name
            with open(output_file, "wb") as f:
                f.write(decompressed_data)
            return f"Decompressed: {path} -> {output_file}"
        else:
            return f"Skipped (not a .7z or .tar.7z file): {path}"
    except Exception as e:
        return f"Error decompressing {path}: {e!s}"


def process_files_parallel(
    files: list[Path],
    output_dir: Path,
    mode: str,
    tar_subdirs_first: bool = False,
) -> list[str]:
    """
    Process a list of files in parallel using a multiprocessing pool.

    Args:
        files: List of file or directory paths to process.
        output_dir: Directory for output files.
        mode: Either "compress" or "decompress".
        tar_subdirs_first: Passed to compress_file when compressing directories.

    Returns:
        A list of result/status strings from the workers.
    """
    results: list[str] = []
    tasks: list[tuple[tuple[Path | str, Path, bool], str]] = []

    if mode == "compress":
        for file in files:
            tasks.append(((file, output_dir, tar_subdirs_first), "compress"))
    else:
        for file in files:
            tasks.append(((file, output_dir), "decompress"))

    with Pool(processes=POOL_WORKERS) as pool:
        async_results = []
        for args, task_mode in tasks:
            if task_mode == "compress":
                async_results.append(pool.apply_async(compress_file, args=args))
            else:
                async_results.append(pool.apply_async(decompress_file, args=args))

        for async_result in async_results:
            result = async_result.get()
            if result:
                results.append(result)
                print(result)

    return results


def _default_output_for_mode(mode: str) -> str:
    """
    Return the default output directory for a given mode.

    Args:
        mode: Either "compress" or "decompress".

    Returns:
        The default output directory path as a string.
    """
    if mode == "decompress":
        return DEFAULT_DECOMPRESS_OUTPUT
    return DEFAULT_COMPRESS_OUTPUT


def build_parser() -> argparse.ArgumentParser:
    """
    Build and return the argument parser for the script.

    Returns:
        A configured argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Compress/decompress files recursively using pylzma "
            "with parallel processing"
        )
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_const",
        const="compress",
        dest="mode",
        default="compress",
        help="Compress files (default mode)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_const",
        const="decompress",
        dest="mode",
        help="Decompress files",
    )
    parser.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        default=False,
        help="Tar subdirectories first before compression",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help=(
            "Output directory (default: ./compressed for compress, "
            "./decompressed for decompress)"
        ),
    )
    return parser


def main() -> int:
    """
    Entry point for the script.

    Parses arguments, discovers files, and dispatches parallel compression
    or decompression.

    Returns:
        Exit status code (0 on success).
    """
    parser = build_parser()
    args = parser.parse_args()

    mode: str = args.mode
    tar_subdirs_first: bool = args.tar_subdirs_first

    output_arg: str | None = args.output
    output_dir = Path(
        output_arg if output_arg is not None else _default_output_for_mode(mode)
    )

    current_dir = Path(".")

    if mode == "compress":
        output_dir.mkdir(exist_ok=True)
        all_files: list[Path] = []
        for item in current_dir.rglob("*"):
            if item.is_file() or (item.is_dir() and not tar_subdirs_first):
                try:
                    if output_dir in item.parents or item == output_dir:
                        continue
                except (ValueError, AttributeError):
                    pass
                if item.is_file():
                    if item.suffix == ".7z":
                        continue
                    all_files.append(item)
                elif item.is_dir() and tar_subdirs_first:
                    if item != current_dir:
                        try:
                            if output_dir not in item.parents and item != output_dir:
                                all_files.append(item)
                        except (ValueError, AttributeError):
                            all_files.append(item)
        if not all_files:
            logger.warning("No files found to compress in current directory")
            return 0
        print(f"Found {len(all_files)} items to compress")
        print(f"Compressing to: {output_dir}")
        process_files_parallel(all_files, output_dir, "compress", tar_subdirs_first)
    else:
        output_dir.mkdir(exist_ok=True)
        compressed_files: list[Path] = []
        for item in current_dir.rglob("*"):
            if item.is_file() and (
                item.suffix == ".7z" or item.name.endswith(".tar.7z")
            ):
                try:
                    if output_dir not in item.parents and item != output_dir:
                        compressed_files.append(item)
                except (ValueError, AttributeError):
                    compressed_files.append(item)
        if not compressed_files:
            logger.warning("No .7z or .tar.7z files found in current directory")
            return 0
        print(f"Found {len(compressed_files)} files to decompress")
        print(f"Decompressing to: {output_dir}")
        process_files_parallel(compressed_files, output_dir, "decompress", False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
