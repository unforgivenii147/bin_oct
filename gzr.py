#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that compresses and decompresses files and directories
using gzip and tar with multiprocessing (8 workers), loguru logging, pathlib paths,
full type hints, and async orchestration. It supports -c (compress) and -d
(decompress) modes, chunked compression for large files, in-memory compression for
small files, folder archival into .tar.gz, and decompression of .gz and .tar.gz
archives.
"""

import asyncio
import gzip
import mmap
import shutil
import sys
import tarfile
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from loguru import logger

MAX_WORKERS: Final[int] = 8
CHUNK_SIZE: Final[int] = 524288
CHUNK_SIZE_SMALL: Final[int] = 32768
GZIP_COMPRESS_LEVEL: Final[int] = 9
MIN_COMPRESS_SIZE: Final[int] = 1024


def fsz(size: int) -> str:
    """Format a byte size into a human-readable string."""
    units: list[str] = ["B", "KB", "MB", "GB", "TB"]
    value: float = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"


def decompress_file(path: Path) -> bool:
    """Decompress a single .gz file in place, removing the original on success."""
    if path.suffix != ".gz":
        return False
    out_path: Path = path.with_suffix("")
    try:
        with gzip.open(path, "rb") as f_in:
            decompressed_data: bytes = f_in.read()
        out_path.write_bytes(decompressed_data)
        original_size: int = path.stat().st_size
        decompressed_size: int = out_path.stat().st_size
        print(
            f"  ✓ Decompressed {path.name}: {fsz(original_size)} → {fsz(decompressed_size)}"
        )
        path.unlink()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
        return False


def compress_in_memory(infile: Path, outfile: Path) -> bool:
    """Compress a small file entirely in memory using gzip."""
    try:
        data: bytes = infile.read_bytes()
        if not data:
            return False
        compressed: bytes = gzip.compress(data, compresslevel=GZIP_COMPRESS_LEVEL)
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data: bytes) -> bytes:
    """Compress a single byte chunk with gzip."""
    return gzip.compress(data, compresslevel=GZIP_COMPRESS_LEVEL)


def _compress_chunk_star(args: tuple[bytes, int]) -> tuple[int, bytes]:
    """Helper to unpack chunk arguments for Pool.apply_async."""
    chunk, idx = args
    return idx, compress_chunk(chunk)


def compress_chunked(in_path: Path, out_path: Path, file_size: int, pool: Pool) -> bool:
    """Compress a large file in parallel chunks using a multiprocessing pool."""
    try:
        chunk_count: int = (file_size + CHUNK_SIZE_SMALL - 1) // CHUNK_SIZE_SMALL
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            chunks: list[bytes] = [
                mm[i * CHUNK_SIZE_SMALL : min((i + 1) * CHUNK_SIZE_SMALL, file_size)]
                for i in range(chunk_count)
            ]
            results: list[bytes | None] = [None] * chunk_count
            async_results: list[AsyncResult[tuple[int, bytes]]] = [
                pool.apply_async(_compress_chunk_star, ((chunk, idx),))
                for idx, chunk in enumerate(chunks)
            ]
            for ar in async_results:
                try:
                    idx, compressed_chunk = ar.get()
                    results[idx] = compressed_chunk
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Chunk compression failed: {e}")
                    return False
            for compressed_chunk in results:
                if compressed_chunk is not None:
                    fout.write(compressed_chunk)
                else:
                    return False
            return True
    except (OSError, MemoryError) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def create_tar_archive(source_dir: Path, output_path: Path) -> bool:
    """Create an uncompressed tar archive from a directory."""
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname: Path = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=str(arcname))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  Failed to create tar archive: {e}")
        return False


def compress_tar_to_gz(tar_path: Path, gz_path: Path, pool: Pool) -> bool:
    """Compress a tar archive to .tar.gz, deleting the tar if compression saves space."""
    try:
        tar_size: int = tar_path.stat().st_size
        if tar_size < CHUNK_SIZE:
            success: bool = compress_in_memory(tar_path, gz_path)
        else:
            success = compress_chunked(tar_path, gz_path, tar_size, pool)
        if success and gz_path.exists():
            gz_size: int = gz_path.stat().st_size
            if gz_size == 0:
                logger.warning(f"Compressed archive empty for {tar_path.name}")
                gz_path.unlink()
                return False
            if gz_size < tar_size:
                tar_path.unlink()
                reduction: float = (tar_size - gz_size) / tar_size * 100
                print(
                    f"  ✓ Compressed archive: {reduction:.1f}% saved ({fsz(tar_size)} → {fsz(gz_size)})"
                )
                return True
            else:
                print("  ✗ Archive compression didn't save space, keeping .tar")
                gz_path.unlink()
                return False
        return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"  ✗ Failed to compress tar archive: {e}")
        return False


async def compress_folder_async(
    folder_path: Path, output_base_name: str, pool: Pool
) -> bool:
    """Asynchronously compress an entire folder into a .tar.gz archive."""
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    tar_path: Path = Path(output_base_name + ".tar")
    gz_path: Path = Path(output_base_name + ".tar.gz")
    try:
        print("  Creating tar archive...")
        success: bool = await loop.run_in_executor(
            None, create_tar_archive, folder_path, tar_path
        )
        if not success or not tar_path.exists():
            logger.error("  Failed to create tar archive")
            return False
        print(f"  Compressing tar archive with gzip (level {GZIP_COMPRESS_LEVEL})...")
        if await loop.run_in_executor(
            None, compress_tar_to_gz, tar_path, gz_path, pool
        ):
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            return True
        else:
            return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        if gz_path.exists():
            gz_path.unlink()
        return False


def compress_file(path: Path, pool: Pool) -> tuple[bool, int, int]:
    """Compress a single file to .gz, returning success and size stats."""
    out_path: Path = path.with_suffix(path.suffix + ".gz")
    if out_path.exists():
        print(f"Skipping {path.name} - output already exists")
        return False, 0, 0
    try:
        original_size: int = path.stat().st_size
        if not original_size:
            return False, 0, 0
        if original_size < CHUNK_SIZE:
            success: bool = compress_in_memory(path, out_path)
        else:
            success = compress_chunked(path, out_path, original_size, pool)
        if success and out_path.exists():
            compressed_size: int = out_path.stat().st_size
            if compressed_size == 0:
                logger.warning(f"Compressed file empty for {path.name}")
                out_path.unlink()
                return False, 0, 0
            if compressed_size < original_size:
                path.unlink()
                reduction: float = (
                    (original_size - compressed_size) / original_size * 100
                )
                print(
                    f"  ✓ {path.name}: {reduction:.1f}% saved ({fsz(original_size)} → {fsz(compressed_size)})"
                )
                return True, original_size, compressed_size
            else:
                print(f"  ✗ {path.name}: No space saved, removing compressed file")
                out_path.unlink()
                return False, 0, 0
        else:
            return False, 0, 0
    except (OSError, PermissionError) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


def get_files(directory: Path, mode: str = "compress") -> list[Path]:
    """Return files from a directory matching the given mode."""
    if mode == "compress":
        return [
            p
            for p in directory.glob("*")
            if p.is_file() and not p.is_symlink() and should_compress(p)
        ]
    else:
        return [p for p in directory.glob("*.gz") if p.is_file() and not p.is_symlink()]


def get_dirs(directory: Path) -> list[Path]:
    """Return all non-symlink subdirectories of a directory."""
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def should_compress(path: Path) -> bool:
    """Return True if a file should be compressed (not already compressed, big enough)."""
    try:
        if not path.is_file() or path.is_symlink():
            return False
        compressed_extensions: tuple[str, ...] = (
            ".gz",
            ".bz2",
            ".xz",
            ".br",
            ".zst",
            ".7z",
            ".zip",
            ".rar",
        )
        if path.suffix in compressed_extensions:
            return False
        size: int = path.stat().st_size
        return size >= MIN_COMPRESS_SIZE
    except (OSError, PermissionError):
        return False


def extract_tar_archive(tar_path: Path, extract_dir: Path) -> bool:
    """Extract a tar archive into a target directory."""
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"  Failed to extract tar archive: {e}")
        return False


async def process_compress(files: list[Path] | None = None) -> None:
    """Compress directories and files in the current working directory."""
    cwd: Path = Path.cwd()
    with Pool(processes=MAX_WORKERS) as pool:
        dirs_to_compress: list[Path] = get_dirs(cwd)
        if dirs_to_compress:
            print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
            for dir_path in sorted(dirs_to_compress):
                relative_path: Path = dir_path.relative_to(cwd)
                print(f"\n  Processing {relative_path}...")
                archive_path: str = str(dir_path.parent / dir_path.name)
                if await compress_folder_async(dir_path, archive_path, pool):
                    print(
                        f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.tar.gz"
                    )
                else:
                    logger.error(f"  ✗ Failed to compress {relative_path}")
        files_to_compress: list[Path] = (
            list(files) if files else get_files(cwd, mode="compress")
        )
        print(
            f"\n📄 Compressing {len(files_to_compress)} files with gzip max compression..."
        )
        total_original: int = 0
        total_compressed: int = 0
        successful: int = 0
        for i, path in enumerate(sorted(files_to_compress), 1):
            print(f"\n[{i}/{len(files_to_compress)}] {path.name}")
            success: bool
            orig_size: int
            comp_size: int
            success, orig_size, comp_size = compress_file(path, pool)
            if success:
                successful += 1
                total_original += orig_size
                total_compressed += comp_size
        if successful > 0:
            savings: int = total_original - total_compressed
            savings_percent: float = savings / total_original * 100
            print(f"\n{'=' * 40}")
            print(f"✅ Compressed {successful}/{len(files_to_compress)} files")
            print(f"📊 Original size:  {fsz(total_original)}")
            print(f"📦 Compressed size: {fsz(total_compressed)}")
            print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
            print(f"{'=' * 40}")
        elif files_to_compress:
            logger.error("\n❌ No files were successfully compressed")


async def process_decompress(files: list[Path] | None = None) -> None:
    """Decompress .tar.gz archives and .gz files in the current working directory."""
    cwd: Path = Path.cwd()
    archives: list[Path] = (
        list(files) if files else [p for p in cwd.glob("*.tar.gz") if p.is_file()]
    )
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for archive in sorted(archives):
            print(f"\n  Decompressing {archive.name}...")
            tar_path: Path | None = None
            try:
                tar_path = archive.with_suffix("")
                print("    Decompressing gzip...")
                with gzip.open(archive, "rb") as f_in:
                    tar_data: bytes = f_in.read()
                tar_path.write_bytes(tar_data)
                extract_dir: str = archive.stem
                print(f"    Extracting tar to {extract_dir}/...")
                loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
                success: bool = await loop.run_in_executor(
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
                if tar_path and tar_path.exists():
                    tar_path.unlink()
    files_to_decompress: list[Path] = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .gz files to decompress")
        return
    files_to_decompress = [
        p for p in files_to_decompress if p.suffixes != [".tar", ".gz"]
    ]
    if not files_to_decompress:
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} gzip files...")
    total_original: int = 0
    total_decompressed: int = 0
    successful: int = 0
    for i, path in enumerate(sorted(files_to_decompress), 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        original_size: int = path.stat().st_size
        total_original += original_size
        if decompress_file(path):
            successful += 1
            out_path: Path = path.with_suffix("")
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


async def main_async(files: list[Path], mode: str = "compress") -> None:
    """Dispatch to the compression or decompression workflow."""
    if mode == "compress":
        await process_compress(files)
    elif mode == "decompress":
        await process_decompress(files)
    else:
        logger.error(f"Unknown mode: {mode}")


def main() -> None:
    """CLI entry point: parse arguments and run the async main routine."""
    cwd: Path = Path.cwd()
    args: list[str] = sys.argv[1:]
    files: list[Path] = []
    mode: str = "compress"
    if args:
        for arg in args:
            if arg == "-c":
                mode = "compress"
                continue
            elif arg == "-d":
                mode = "decompress"
                continue
            else:
                p: Path = Path(arg)
                if p.is_file():
                    files.append(p)
                if p.is_dir():
                    files.extend(get_files(p))
    else:
        files = get_files(cwd)
    if not files:
        print("no files found")
        sys.exit(0)
    try:
        asyncio.run(main_async(files, mode))
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        logger.error(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
