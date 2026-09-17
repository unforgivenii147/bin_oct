#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI tool for multi-threaded compression/decompression using
multiprocessing.Pool.apply_async with 8 workers, loguru for logging, pathlib
for paths, full type hints, and docstrings. Features: compress files (>1KB,
non-archives) and folders (tar + xz) in CWD; decompress .xz and .tar.xz
archives in CWD; chunked xz compression for files >=1MB via 32KB chunks; skip
files when output exists or no space is saved; recursive folder archiving;
cleanup of intermediates on success; summary stats; CLI flags -c/--compress
(default) and -d/--decompress.
"""

from __future__ import annotations

import argparse
import asyncio
import mmap
import shutil
import sys
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from dh import fsz
from loguru import logger
from lzma_mt import compress, decompress  # type: ignore[import-not-found]

MAX_WORKERS: Final[int] = 8
CHUNK_SIZE: Final[int] = 1048576
SMALL_CHUNK_SIZE: Final[int] = 32768
COMPRESSED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".xz",
    ".br",
    ".7z",
    ".gz",
    ".zip",
    ".tar",
)
MIN_COMPRESS_SIZE: Final[int] = 1024

_pool: Pool | None = None


def get_pool() -> Pool:
    """Return a lazily-initialized global multiprocessing pool."""
    global _pool
    if _pool is None:
        _pool = Pool(processes=MAX_WORKERS)
    return _pool


def close_pool() -> None:
    """Close and join the global pool if it exists."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool.join()
        _pool = None


def decompress_file(path: Path) -> bool:
    """Decompress a single .xz file in place, removing the source on success."""
    if path.suffix != ".xz":
        return False
    out_path = path.with_suffix("")
    try:
        compressed_data = path.read_bytes()
        if not compressed_data:
            return False
        decompressed_data = decompress(compressed_data)
        out_path.write_bytes(decompressed_data)
        original_size = path.stat().st_size
        decompressed_size = out_path.stat().st_size
        print(
            f"  ✓ Decompressed {path.name}: "
            f"{fsz(original_size)} → {fsz(decompressed_size)}"
        )
        path.unlink()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
        return False


def compress_in_memory(infile: Path, outfile: Path) -> bool:
    """Compress a small file entirely in memory."""
    try:
        data = infile.read_bytes()
        if not data:
            return False
        compressed = compress(data, preset=9, threads=4)
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data: bytes) -> bytes:
    """Compress a single chunk of bytes with xz."""
    return compress(data, preset=9, threads=6)


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    """Compress a large file by splitting it into chunks processed in parallel."""
    try:
        chunk_count = (file_size + SMALL_CHUNK_SIZE - 1) // SMALL_CHUNK_SIZE
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks = [
                mm[i * SMALL_CHUNK_SIZE : min((i + 1) * SMALL_CHUNK_SIZE, file_size)]
                for i in range(chunk_count)
            ]
            pool = get_pool()
            async_results = [
                pool.apply_async(compress_chunk, (chunk,)) for chunk in chunks
            ]
            results: list[bytes | None] = []
            for idx, ar in enumerate(async_results):
                try:
                    results.append(ar.get())
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Chunk {idx} compression failed: {e}")
                    return False
            for compressed_chunk in results:
                if compressed_chunk:
                    fout.write(compressed_chunk)
                else:
                    return False
            return True
    except (OSError, MemoryError) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    """Create a .tar archive containing all files under source_dir."""
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=arcname)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  Failed to create tar archive: {e}")
        return False


def compress_tar_to_xz(tar_path: Path, xz_path: Path) -> bool:
    """Compress a .tar file to .tar.xz, deleting the .tar on success."""
    try:
        tar_size = tar_path.stat().st_size
        if tar_size < CHUNK_SIZE:
            success = compress_in_memory(tar_path, xz_path)
        else:
            success = compress_chunked(tar_path, xz_path, tar_size)
        if success and xz_path.exists():
            xz_size = xz_path.stat().st_size
            if xz_size == 0:
                logger.warning(f"Warning: Compressed archive empty for {tar_path.name}")
                xz_path.unlink()
                return False
            if xz_size < tar_size:
                tar_path.unlink()
                reduction = (tar_size - xz_size) / tar_size * 100
                print(
                    f"  ✓ Compressed archive: {reduction:.1f}% saved "
                    f"({fsz(tar_size)} → {fsz(xz_size)})"
                )
                return True
            else:
                print("  ✗ Archive compression didn't save space, keeping .tar")
                xz_path.unlink()
                return False
        return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"  ✗ Failed to compress tar archive: {e}")
        return False


async def compress_folder_async(folder_path: Path, output_base_name: str) -> bool:
    """Asynchronously archive and compress a folder to .tar.xz."""
    loop = asyncio.get_running_loop()
    tar_path = Path(output_base_name + ".tar")
    xz_path = Path(output_base_name + ".tar.xz")
    try:
        print("  Creating tar archive...")
        success = await loop.run_in_executor(
            None, create_tar_archive, folder_path, tar_path
        )
        if not success or not tar_path.exists():
            logger.error("  Failed to create tar archive")
            return False
        print("  Compressing tar archive...")
        if await loop.run_in_executor(None, compress_tar_to_xz, tar_path, xz_path):
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        if xz_path.exists():
            xz_path.unlink()
        return False


def compress_file(path: Path) -> tuple[bool, int, int]:
    """Compress a single file to .xz; return (success, original, compressed)."""
    out_path = path.with_name(path.name + ".xz")
    if out_path.exists():
        print(f"Skipping {path.name} - output already exists")
        return False, 0, 0
    try:
        original_size = path.stat().st_size
        if not original_size:
            return False, 0, 0
        if original_size < CHUNK_SIZE:
            success = compress_in_memory(path, out_path)
        else:
            success = compress_chunked(path, out_path, original_size)
        if success and out_path.exists():
            compressed_size = out_path.stat().st_size
            if compressed_size == 0:
                logger.warning(f"Warning: Compressed file empty for {path.name}")
                out_path.unlink()
                return False, 0, 0
            if compressed_size < original_size:
                reduction = (original_size - compressed_size) / original_size * 100
                print(
                    f"  ✓ {path.name}: {reduction:.1f}% saved "
                    f"({fsz(original_size)} → {fsz(compressed_size)})"
                )
                path.unlink()
                return True, original_size, compressed_size
            else:
                print(f"  ✗ {path.name}: No space saved, removing compressed file")
                out_path.unlink()
                return False, 0, 0
        return False, 0, 0
    except (OSError, PermissionError) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


def get_files_local(directory: Path, mode: str = "compress") -> list[Path]:
    """Return candidate files in a directory for compression or decompression."""
    if mode == "compress":
        return [
            p
            for p in directory.glob("*")
            if p.is_file() and not p.is_symlink() and should_compress(p)
        ]
    else:
        return [p for p in directory.glob("*.xz") if p.is_file() and not p.is_symlink()]


def get_dirs(directory: Path) -> list[Path]:
    """Return non-symlink subdirectories of directory."""
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def should_compress(path: Path) -> bool:
    """Return True if path is a file eligible for compression."""
    try:
        if not path.is_file() or path.is_symlink():
            return False
        if path.suffix in COMPRESSED_EXTENSIONS:
            return False
        size = path.stat().st_size
        return size >= MIN_COMPRESS_SIZE
    except (OSError, PermissionError):
        return False


def extract_tar_archive(tar_path: Path, extract_dir: Path) -> bool:
    """Extract a tar archive into extract_dir."""
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  Failed to extract tar archive: {e}")
        return False


async def process_compress() -> None:
    """Compress all eligible folders and files in the current directory."""
    cwd = Path.cwd()
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in sorted(dirs_to_compress):
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            archive_path = str(dir_path.parent / dir_path.name)
            if await compress_folder_async(dir_path, archive_path):
                print(
                    f"  ✓ Successfully compressed {relative_path} to "
                    f"{dir_path.name}.tar.xz"
                )
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files_local(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(f"\n📄 Compressing {len(files_to_compress)} files...")
    total_original = 0
    total_compressed = 0
    successful = 0
    for i, path in enumerate(sorted(files_to_compress), 1):
        print(f"\n[{i}/{len(files_to_compress)}] {path.name}")
        success, orig_size, comp_size = compress_file(path)
        if success:
            successful += 1
            total_original += orig_size
            total_compressed += comp_size
    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = savings / total_original * 100
        print(f"\n{'=' * 40}")
        print(f"✅ Compressed {successful}/{len(files_to_compress)} files")
        print(f"📊 Original size:  {fsz(total_original)}")
        print(f"📦 Compressed size: {fsz(total_compressed)}")
        print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
        print(f"{'=' * 40}")
    elif files_to_compress:
        logger.error("\n❌ No files were successfully compressed")


async def process_decompress() -> None:
    """Decompress all .tar.xz archives and standalone .xz files in CWD."""
    cwd = Path.cwd()
    archives = [p for p in cwd.glob("*.tar.xz") if p.is_file()]
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for archive in sorted(archives):
            print(f"\n  Decompressing {archive.name}...")
            tar_path: Path | None = None
            try:
                tar_path = archive.with_suffix("")
                print("    Decompressing xz...")
                compressed_data = archive.read_bytes()
                tar_data = decompress(compressed_data)
                tar_path.write_bytes(tar_data)
                extract_dir = archive.stem
                print(f"    Extracting tar to {extract_dir}/...")
                loop = asyncio.get_running_loop()
                success = await loop.run_in_executor(
                    None, extract_tar_archive, tar_path, Path(extract_dir)
                )
                if success:
                    tar_path.unlink()
                    archive.unlink()
                    print(f"  ✓ Extracted {archive.name} to {extract_dir}/")
                else:
                    logger.error(f"  ✗ Failed to extract {archive.name}")
            except Exception as e:  # noqa: BLE001
                logger.error(f"  ✗ Failed to decompress {archive.name}: {e}")
                if tar_path is not None and tar_path.exists():
                    tar_path.unlink()
    files_to_decompress = get_files_local(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .xz files to decompress")
        return
    files_to_decompress = [
        p for p in files_to_decompress if p.suffixes != [".tar", ".xz"]
    ]
    if not files_to_decompress:
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} files...")
    total_original = 0
    total_decompressed = 0
    successful = 0
    for i, path in enumerate(sorted(files_to_decompress), 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        original_size = path.stat().st_size
        total_original += original_size
        if decompress_file(path):
            successful += 1
            out_path = path.with_suffix("")
            if out_path.exists():
                total_decompressed += out_path.stat().st_size
    if successful > 0:
        print(f"\n{'=' * 40}")
        print(f"✅ Decompressed {successful}/{len(files_to_decompress)} files")
        print(f"📦 Compressed size:   {fsz(total_original)}")
        print(f"📊 Decompressed size: {fsz(total_decompressed)}")
        print(f"{'=' * 40}")
    elif files_to_decompress:
        logger.error("\n❌ No files were successfully decompressed")


async def main_async(mode: str = "compress") -> None:
    """Dispatch to compress or decompress processing based on mode."""
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def main() -> None:
    """Parse CLI arguments and run the selected async workflow."""
    parser = argparse.ArgumentParser(
        description="Multi-threaded compression/decompression tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .xz and .tar.xz files",
    )
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    try:
        asyncio.run(main_async(mode))
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        logger.error(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
