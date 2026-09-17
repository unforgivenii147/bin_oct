#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a multi-threaded LZ4 compression/decompression CLI tool with the following spec:
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for parallel chunk compression.
- Provide compress mode (default) that compresses files >=1KB and non-compressed extensions in CWD, and tars+compresses directories to .tar.lz4.
- Provide decompress mode that extracts .tar.lz4 archives and decompresses .lz4 files.
- Use LZ4 max compression (level 9, high_compression, block size 4MB, block_linked, content_checksum).
- Use pathlib for all path handling, loguru for logging, full strict type hints, and no CLI args controlling parallelism.
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

import lz4.frame
from loguru import logger

MAX_WORKERS: Final[int] = 8
CHUNK_SIZE: Final[int] = 524288
CHUNK_SIZE_SMALL: Final[int] = 32768
LZ4_COMPRESS_LEVEL: Final[int] = 9
LZ4_ACCELERATION: Final[int] = 1
COMPRESSED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".lz4",
    ".xz",
    ".gz",
    ".bz2",
    ".br",
    ".zst",
    ".7z",
    ".zip",
    ".rar",
)
MIN_COMPRESS_SIZE: Final[int] = 1024


def fsz(size: int) -> str:
    """Format a byte size into a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} {units[-1]}"


def decompress_file(path: Path) -> bool:
    """Decompress a single .lz4 file in place, removing the compressed file on success."""
    if path.suffix != ".lz4":
        return False
    out_path = path.with_suffix("")
    try:
        compressed_data = path.read_bytes()
        if not compressed_data:
            return False
        decompressed_data = lz4.frame.decompress(compressed_data)
        out_path.write_bytes(decompressed_data)
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


def compress_in_memory(infile: Path, outfile: Path) -> bool:
    """Compress a small file entirely in memory using LZ4 max compression."""
    try:
        data = infile.read_bytes()
        if not data:
            return False
        compressed = lz4.frame.compress(
            data,
            compression_level=LZ4_COMPRESS_LEVEL,
            mode="high_compression",
            acceleration=LZ4_ACCELERATION,
            content_checksum=True,
            block_size=lz4.frame.BLOCKSIZE_MAX,
            block_linked=True,
        )
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError, lz4.frame.LZ4FrameError) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data: bytes) -> bytes:
    """Compress a single byte chunk with LZ4 max compression settings."""
    return lz4.frame.compress(
        data,
        compression_level=LZ4_COMPRESS_LEVEL,
        mode="high_compression",
        acceleration=LZ4_ACCELERATION,
        content_checksum=True,
        block_size=lz4.frame.BLOCKSIZE_MAX,
        block_linked=True,
    )


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    """Compress a large file in parallel chunks using a multiprocessing pool."""
    try:
        chunk_count = (file_size + CHUNK_SIZE_SMALL - 1) // CHUNK_SIZE_SMALL
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks = [
                mm[i * CHUNK_SIZE_SMALL : min((i + 1) * CHUNK_SIZE_SMALL, file_size)]
                for i in range(chunk_count)
            ]
            with Pool(processes=MAX_WORKERS) as pool:
                async_results = [
                    pool.apply_async(compress_chunk, (chunk,)) for chunk in chunks
                ]
                results: list[bytes | None] = [None] * chunk_count
                for idx, async_result in enumerate(async_results):
                    try:
                        results[idx] = async_result.get()
                    except Exception as e:
                        logger.error(f"Chunk {idx} compression failed: {e}")
                        return False
            for compressed_chunk in results:
                if compressed_chunk:
                    fout.write(compressed_chunk)
                else:
                    return False
            return True
    except (OSError, MemoryError, lz4.frame.LZ4FrameError) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    """Create a tar archive of the given directory."""
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=arcname)
        return True
    except Exception as e:
        logger.error(f"  Failed to create tar archive: {e}")
        return False


def compress_tar_to_lz4(tar_path: Path, lz4_path: Path) -> bool:
    """Compress a tar archive to LZ4, deleting the tar if compression saves space."""
    try:
        tar_size = tar_path.stat().st_size
        if tar_size < CHUNK_SIZE:
            success = compress_in_memory(tar_path, lz4_path)
        else:
            success = compress_chunked(tar_path, lz4_path, tar_size)
        if success and lz4_path.exists():
            lz4_size = lz4_path.stat().st_size
            if lz4_size == 0:
                logger.warning(f"Compressed archive empty for {tar_path.name}")
                lz4_path.unlink()
                return False
            if lz4_size < tar_size:
                tar_path.unlink()
                reduction = (tar_size - lz4_size) / tar_size * 100
                print(
                    f"  ✓ Compressed archive: {reduction:.1f}% saved ({fsz(tar_size)} → {fsz(lz4_size)})"
                )
                return True
            else:
                logger.warning(
                    "  ✗ Archive compression didn't save space, keeping .tar"
                )
                lz4_path.unlink()
                return False
        return False
    except Exception as e:
        logger.error(f"  ✗ Failed to compress tar archive: {e}")
        return False


async def compress_folder_async(folder_path: Path, output_base_name: str) -> bool:
    """Asynchronously tar and LZ4-compress a folder, deleting the folder on success."""
    loop = asyncio.get_running_loop()
    tar_path = Path(output_base_name + ".tar")
    lz4_path = Path(output_base_name + ".tar.lz4")
    try:
        print("  Creating tar archive...")
        success = await loop.run_in_executor(
            None, create_tar_archive, folder_path, tar_path
        )
        if not success or not tar_path.exists():
            logger.error("  Failed to create tar archive")
            return False
        print("  Compressing tar archive with LZ4 (max compression)...")
        if compress_tar_to_lz4(tar_path, lz4_path):
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        if lz4_path.exists():
            lz4_path.unlink()
        return False


def compress_file(path: Path) -> tuple[bool, int, int]:
    """Compress a single file to .lz4, deleting the original if space is saved."""
    out_path = path.with_suffix(path.suffix + ".lz4")
    if out_path.exists():
        logger.warning(f"Skipping {path.name} - output already exists")
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
                logger.warning(f"Compressed file empty for {path.name}")
                out_path.unlink()
                return False, 0, 0
            if compressed_size < original_size:
                path.unlink()
                reduction = (original_size - compressed_size) / original_size * 100
                print(
                    f"  ✓ {path.name}: {reduction:.1f}% saved ({fsz(original_size)} → {fsz(compressed_size)})"
                )
                return True, original_size, compressed_size
            else:
                logger.warning(
                    f"  ✗ {path.name}: No space saved, removing compressed file"
                )
                out_path.unlink()
                return False, 0, 0
        else:
            return False, 0, 0
    except (OSError, PermissionError, lz4.frame.LZ4FrameError) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


def get_files(directory: Path, mode: str = "compress") -> list[Path]:
    """Return files to process in the given mode ('compress' or 'decompress')."""
    if mode == "compress":
        return [
            p
            for p in directory.glob("*")
            if p.is_file() and not p.is_symlink() and should_compress(p)
        ]
    else:
        return [
            p for p in directory.glob("*.lz4") if p.is_file() and not p.is_symlink()
        ]


def get_dirs(directory: Path) -> list[Path]:
    """Return non-symlink subdirectories of the given directory."""
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def should_compress(path: Path) -> bool:
    """Return True if the path is a compressible file of at least 1KB."""
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
    """Extract a tar archive into the given directory."""
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except Exception as e:
        logger.error(f"  Failed to extract tar archive: {e}")
        return False


async def process_compress() -> None:
    """Compress all eligible directories and files in the current working directory."""
    cwd = Path.cwd()
    print("\n🔧 LZ4 Compression Settings:")
    print(f"   Level: {LZ4_COMPRESS_LEVEL}/9 (maximum)")
    print("   Mode: High Compression (HC)")
    print(f"   Acceleration: {LZ4_ACCELERATION} (slowest/max compression)")
    print("   Block size: Max (4MB)")
    print("   Block linking: Enabled")
    print("   Content checksum: Enabled")
    print(f"   Parallel workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in sorted(dirs_to_compress):
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            archive_path = str(dir_path.parent / dir_path.name)
            if await compress_folder_async(dir_path, archive_path):
                print(
                    f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.tar.lz4"
                )
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(
        f"\n📄 Compressing {len(files_to_compress)} files with LZ4 max compression..."
    )
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
        savings_percent = savings / total_original * 100 if total_original else 0.0
        print(f"\n{'=' * 40}")
        print(f"✅ Compressed {successful}/{len(files_to_compress)} files")
        print(f"📊 Original size:  {fsz(total_original)}")
        print(f"📦 Compressed size: {fsz(total_compressed)}")
        print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
        print(f"{'=' * 40}")
    elif files_to_compress:
        logger.error("\n❌ No files were successfully compressed")


async def process_decompress() -> None:
    """Decompress all .tar.lz4 archives and .lz4 files in the current working directory."""
    cwd = Path.cwd()
    archives = [p for p in cwd.glob("*.tar.lz4") if p.is_file()]
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for archive in sorted(archives):
            print(f"\n  Decompressing {archive.name}...")
            tar_path: Path | None = None
            try:
                tar_path = archive.with_suffix("")
                print("    Decompressing LZ4...")
                compressed_data = archive.read_bytes()
                tar_data = lz4.frame.decompress(compressed_data)
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
            except Exception as e:
                logger.error(f"  ✗ Failed to decompress {archive.name}: {e}")
                if tar_path is not None and tar_path.exists():
                    tar_path.unlink()
    files_to_decompress = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .lz4 files to decompress")
        return
    files_to_decompress = [
        p for p in files_to_decompress if p.suffixes != [".tar", ".lz4"]
    ]
    if not files_to_decompress:
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} LZ4 files...")
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
    """Dispatch to the compress or decompress async workflow."""
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def main() -> None:
    """Parse CLI arguments and run the selected async workflow."""
    parser = argparse.ArgumentParser(
        description="Multi-threaded LZ4 compression/decompression tool (max compression)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
LZ4 Settings:
  - Level: 9 (maximum high compression)
  - Mode: High Compression (HC) for better ratios
  - Acceleration: 1 (slowest/max compression)
  - Block size: 4MB (maximum)
  - Content checksum: Enabled for integrity
  - Use case: Excellent balance of speed and compression
  - Note: Decompression is extremely fast (often > 500 MB/s)
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with LZ4 (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .lz4 and .tar.lz4 files",
    )
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    try:
        asyncio.run(main_async(mode))
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
