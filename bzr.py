#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a multi-threaded bzip2 compression/decompression CLI tool using Python's
standard library plus loguru. The script compresses files and directories with
maximum bzip2 compression (level 9), using multiprocessing.Pool.apply_async with a
fixed pool of 8 workers for chunked compression of large files; small files are
compressed in memory. Directories are tarred then compressed to .tar.bz2. It also
decompresses .bz2 and .tar.bz2 archives, removing originals on success. It uses
pathlib for all path handling, loguru for logging, full type hints, docstrings, and
a CLI with mutually exclusive -c/--compress and -d/--decompress flags (compress is
the default). Path handling never uses os.path. No worker/job CLI flags exist.
"""

from __future__ import annotations

import argparse
import asyncio
import bz2
import mmap
import shutil
import sys
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger

MAX_WORKERS: Final[int] = 8
CHUNK_SIZE: Final[int] = 524288
COMPRESS_CHUNK_SIZE: Final[int] = 32768
BZ2_COMPRESS_LEVEL: Final[int] = 9

COMPRESSED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".bz2",
    ".xz",
    ".gz",
    ".br",
    ".zst",
    ".7z",
    ".zip",
    ".rar",
)

_pool: Pool | None = None


def get_pool() -> Pool:
    """Return a lazily-initialized global multiprocessing pool."""
    global _pool
    if _pool is None:
        _pool = Pool(processes=MAX_WORKERS)
    return _pool


def close_pool() -> None:
    """Close and join the global multiprocessing pool if it exists."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool.join()
        _pool = None


def fsz(size: int) -> str:
    """Format a byte size into a human-readable string."""
    units: list[str] = ["B", "KB", "MB", "GB", "TB"]
    value: float = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"


def decompress_file(path: Path) -> bool:
    """Decompress a single .bz2 file in place, removing the original on success."""
    if path.suffix != ".bz2":
        return False
    out_path = path.with_suffix("")
    try:
        compressed_data = path.read_bytes()
        if not compressed_data:
            return False
        decompressed_data = bz2.decompress(compressed_data)
        out_path.write_bytes(decompressed_data)
        original_size = path.stat().st_size
        decompressed_size = out_path.stat().st_size
        print(
            f"  ✓ Decompressed {path.name}: {fsz(original_size)} → {fsz(decompressed_size)}"
        )
        path.unlink()
        return True
    except (OSError, EOFError, ValueError) as e:
        logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
        return False


def compress_in_memory(infile: Path, outfile: Path) -> bool:
    """Compress a small file entirely in memory into outfile."""
    try:
        data = infile.read_bytes()
        if not data:
            return False
        compressed = bz2.compress(data, compresslevel=BZ2_COMPRESS_LEVEL)
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError, EOFError) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data: bytes) -> bytes:
    """Compress a single byte chunk with bzip2 at maximum level."""
    return bz2.compress(data, compresslevel=BZ2_COMPRESS_LEVEL)


def _compress_chunk_task(args: tuple[int, bytes]) -> tuple[int, bytes]:
    """Worker wrapper returning the chunk index alongside the compressed bytes."""
    idx, chunk = args
    return idx, compress_chunk(chunk)


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    """Compress a large file by splitting it into chunks processed via a pool."""
    try:
        chunk_count = (file_size + COMPRESS_CHUNK_SIZE - 1) // COMPRESS_CHUNK_SIZE
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks: list[tuple[int, bytes]] = [
                (
                    i,
                    mm[
                        i * COMPRESS_CHUNK_SIZE : min(
                            (i + 1) * COMPRESS_CHUNK_SIZE, file_size
                        )
                    ],
                )
                for i in range(chunk_count)
            ]
            pool = get_pool()
            async_results = [
                pool.apply_async(_compress_chunk_task, ((idx, chunk),))
                for idx, chunk in chunks
            ]
            results: list[bytes | None] = [None] * chunk_count
            for async_result in async_results:
                try:
                    idx, compressed_chunk = async_result.get()
                    results[idx] = compressed_chunk
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Chunk compression failed: {e}")
                    return False
            for compressed_chunk in results:
                if compressed_chunk:
                    fout.write(compressed_chunk)
                else:
                    return False
            return True
    except (OSError, MemoryError, EOFError) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    """Create an uncompressed tar archive containing all files under source_dir."""
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=arcname)
        return True
    except (OSError, tarfile.TarError) as e:
        logger.error(f"  Failed to create tar archive: {e}")
        return False


def compress_tar_to_bz2(tar_path: Path, bz2_path: Path) -> bool:
    """Compress a tar archive to .tar.bz2, deleting the tar if space is saved."""
    try:
        tar_size = tar_path.stat().st_size
        if tar_size < CHUNK_SIZE:
            success = compress_in_memory(tar_path, bz2_path)
        else:
            success = compress_chunked(tar_path, bz2_path, tar_size)
        if success and bz2_path.exists():
            bz2_size = bz2_path.stat().st_size
            if bz2_size == 0:
                logger.warning(f"Compressed archive empty for {tar_path.name}")
                bz2_path.unlink()
                return False
            if bz2_size < tar_size:
                tar_path.unlink()
                reduction = (tar_size - bz2_size) / tar_size * 100
                print(
                    f"  ✓ Compressed archive: {reduction:.1f}% saved "
                    f"({fsz(tar_size)} → {fsz(bz2_size)})"
                )
                return True
            print("  ✗ Archive compression didn't save space, keeping .tar")
            bz2_path.unlink()
            return False
        return False
    except (OSError, MemoryError, EOFError, tarfile.TarError) as e:
        logger.error(f"  ✗ Failed to compress tar archive: {e}")
        return False


async def compress_folder_async(folder_path: Path, output_base_name: str) -> bool:
    """Tar and bzip2-compress a directory, deleting it on success."""
    loop = asyncio.get_running_loop()
    tar_path = Path(output_base_name + ".tar")
    bz2_path = Path(output_base_name + ".tar.bz2")
    try:
        print("  Creating tar archive...")
        success = await loop.run_in_executor(
            None, create_tar_archive, folder_path, tar_path
        )
        if not success or not tar_path.exists():
            logger.error("  Failed to create tar archive")
            return False
        print(f"  Compressing tar archive with bzip2 (level {BZ2_COMPRESS_LEVEL})...")
        if compress_tar_to_bz2(tar_path, bz2_path):
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            return True
        return False
    except (OSError, MemoryError, EOFError, tarfile.TarError) as e:
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        if bz2_path.exists():
            bz2_path.unlink()
        return False


def compress_file(path: Path) -> tuple[bool, int, int]:
    """Compress a single file to .bz2, returning (success, orig_size, comp_size)."""
    out_path = path.with_suffix(path.suffix + ".bz2")
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
                logger.warning(f"Compressed file empty for {path.name}")
                out_path.unlink()
                return False, 0, 0
            if compressed_size < original_size:
                path.unlink()
                reduction = (original_size - compressed_size) / original_size * 100
                print(
                    f"  ✓ {path.name}: {reduction:.1f}% saved "
                    f"({fsz(original_size)} → {fsz(compressed_size)})"
                )
                return True, original_size, compressed_size
            print(f"  ✗ {path.name}: No space saved, removing compressed file")
            out_path.unlink()
            return False, 0, 0
        return False, 0, 0
    except (OSError, PermissionError, EOFError) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


def should_compress(path: Path) -> bool:
    """Return True if the path is a regular, non-symlink file worth compressing."""
    try:
        if not path.is_file() or path.is_symlink():
            return False
        if path.suffix in COMPRESSED_EXTENSIONS:
            return False
        size = path.stat().st_size
        return size >= 1024
    except (OSError, PermissionError):
        return False


def get_files(directory: Path, mode: str = "compress") -> list[Path]:
    """Return files in directory eligible for compression or decompression."""
    if mode == "compress":
        return [
            p
            for p in directory.glob("*")
            if p.is_file() and not p.is_symlink() and should_compress(p)
        ]
    return [p for p in directory.glob("*.bz2") if p.is_file() and not p.is_symlink()]


def get_dirs(directory: Path) -> list[Path]:
    """Return non-symlink subdirectories of directory."""
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def extract_tar_archive(tar_path: Path, extract_dir: Path) -> bool:
    """Extract a tar archive into the given directory."""
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except (OSError, tarfile.TarError) as e:
        logger.error(f"  Failed to extract tar archive: {e}")
        return False


async def process_compress() -> None:
    """Compress all eligible directories and files in the current directory."""
    cwd = Path.cwd()
    print("\n🔧 Bzip2 Compression Settings:")
    print(f"   Level: {BZ2_COMPRESS_LEVEL}/9 (maximum)")
    print("   Block size: 900KB (standard)")
    print(f"   Parallel workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")
    print("   Algorithm: Burrows-Wheeler + Run-length + Huffman")
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
                    f"{dir_path.name}.tar.bz2"
                )
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(
        f"\n📄 Compressing {len(files_to_compress)} files with bzip2 max compression..."
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
    """Decompress .tar.bz2 archives and .bz2 files in the current directory."""
    cwd = Path.cwd()
    archives = [p for p in cwd.glob("*.tar.bz2") if p.is_file()]
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for archive in sorted(archives):
            print(f"\n  Decompressing {archive.name}...")
            tar_path: Path | None = None
            try:
                tar_path = archive.with_suffix("")
                print("    Decompressing bzip2...")
                compressed_data = archive.read_bytes()
                tar_data = bz2.decompress(compressed_data)
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
            except (OSError, EOFError, ValueError, tarfile.TarError) as e:
                logger.error(f"  ✗ Failed to decompress {archive.name}: {e}")
                if tar_path is not None and tar_path.exists():
                    tar_path.unlink()
    files_to_decompress = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .bz2 files to decompress")
        return
    files_to_decompress = [
        p for p in files_to_decompress if p.suffixes != [".tar", ".bz2"]
    ]
    if not files_to_decompress:
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} bzip2 files...")
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
    """Dispatch to the requested compression or decompression workflow."""
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def main() -> None:
    """Parse CLI arguments and run the async workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Multi-threaded Bzip2 compression/decompression tool (max compression)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
Bzip2 Settings:
  - Level: 9 (maximum compression)
  - Block size: 900KB
  - Algorithm: Burrows-Wheeler transform + Move-to-front + Huffman coding
  - Good for: Text files, source code, structured data
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with bzip2 (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .bz2 and .tar.bz2 files",
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
