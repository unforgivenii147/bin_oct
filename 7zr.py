#!/data/data/com.termux/files/home/.local/bin/python
"""Multi-threaded 7-Zip compression/decompression tool.

Generate a Python script that compresses and decompresses files and folders
using py7zr with maximum LZMA2 compression settings (preset 9, 256MB
dictionary, solid, header compression, 4MB blocks). Use multiprocessing.Pool
with 8 workers for parallel chunk compression. Provide a CLI with -c/--compress
(default) and -d/--decompress modes. Chunk large files via mmap at 512KB
(CHUNK_SIZE), compress small files in memory, and compress folders recursively.
Only compress files >= 1KB that are not already compressed (.7z, .xz, .gz,
.bz2, .br, .zst, .zip, .rar). Skip compression when no space is saved. Use
loguru for logging, pathlib for paths, and full type annotations with
docstrings. Include a fsz() helper for human-readable file sizes. Use a
temporary directory under the system temp path named py7zr_temp.
"""

from __future__ import annotations

import argparse
import asyncio
import mmap
import shutil
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

import py7zr
from loguru import logger

MAX_WORKERS: Final[int] = 8
CHUNK_SIZE: Final[int] = 524288
SMALL_FILE_THRESHOLD: Final[int] = 32768
TEMP_DIR: Final[Path] = Path(tempfile.gettempdir()) / "py7zr_temp"
SEVENZ_SETTINGS: Final[dict[str, Any]] = {
    "filters": [{"id": py7zr.FILTER_LZMA2, "preset": 9}],
    "dictionary_size": 256 * 1024 * 1024,
    "solid": True,
    "header_compression": True,
    "block_size": 4 * 1024 * 1024,
}
COMPRESSED_EXTENSIONS: Final[tuple[str, ...]] = (
    ".7z",
    ".xz",
    ".gz",
    ".bz2",
    ".br",
    ".zst",
    ".zip",
    ".rar",
)

_POOL: Pool | None = None


def fsz(size: float) -> str:
    """Format a byte count into a human-readable string.

    Args:
        size: Size in bytes.

    Returns:
        Formatted string such as ``"1.50 MB"``.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def _get_pool() -> Pool:
    """Return the module-level multiprocessing pool, creating it lazily.

    Returns:
        A shared ``multiprocessing.Pool`` with ``MAX_WORKERS`` workers.
    """
    global _POOL
    if _POOL is None:
        _POOL = Pool(processes=MAX_WORKERS)
    return _POOL


def _close_pool() -> None:
    """Close and join the module-level multiprocessing pool if it exists."""
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL.join()
        _POOL = None


def should_compress(path: Path) -> bool:
    """Return whether a file is a candidate for compression.

    Args:
        path: Candidate file path.

    Returns:
        True if the file is a regular non-symlink file of at least 1KB
        that does not already have a compressed extension.
    """
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
    """List files in a directory for compression or decompression.

    Args:
        directory: Directory to scan.
        mode: Either ``"compress"`` or ``"decompress"``.

    Returns:
        Sorted list of matching files.
    """
    if mode == "compress":
        return sorted(
            p
            for p in directory.glob("*")
            if p.is_file() and not p.is_symlink() and should_compress(p)
        )
    return sorted(
        p for p in directory.glob("*.7z") if p.is_file() and not p.is_symlink()
    )


def get_dirs(directory: Path) -> list[Path]:
    """List immediate subdirectories of a directory.

    Args:
        directory: Directory to scan.

    Returns:
        Sorted list of subdirectory paths.
    """
    return sorted(p for p in directory.glob("*") if not p.is_symlink() and p.is_dir())


def decompress_file(path: Path) -> bool:
    """Decompress a single .7z archive in place.

    Args:
        path: Path to the ``.7z`` file.

    Returns:
        True on success, False otherwise.
    """
    if path.suffix != ".7z":
        return False
    out_path = path.with_suffix("")
    try:
        with (
            py7zr.SevenZipFile(path, mode="r") as sevenz,
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            sevenz.extractall(path=tmpdir)
            extracted = Path(tmpdir) / out_path.name
            if extracted.exists():
                shutil.move(str(extracted), str(out_path))
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
    """Compress a small file by reading it fully into memory.

    Args:
        infile: Source file path.
        outfile: Destination ``.7z`` path.

    Returns:
        True on success, False otherwise.
    """
    try:
        data = infile.read_bytes()
        if not data:
            return False
        with tempfile.NamedTemporaryFile(delete=False, suffix=".7z") as tmp:
            tmp_path = Path(tmp.name)
        try:
            with py7zr.SevenZipFile(
                tmp_path,
                mode="w",
                filters=SEVENZ_SETTINGS["filters"],
                dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
                solid=SEVENZ_SETTINGS["solid"],
                header_compression=SEVENZ_SETTINGS["header_compression"],
            ) as sevenz:
                sevenz.write(infile, arcname=infile.name)
            compressed = tmp_path.read_bytes()
            outfile.write_bytes(compressed)
            return True
        finally:
            tmp_path.unlink(missing_ok=True)
    except (OSError, MemoryError, py7zr.Bad7zFile) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data: bytes, chunk_id: int, temp_dir: Path) -> Path:
    """Compress a single data chunk into a temporary .7z archive.

    This function is intended to be executed inside a worker process,
    so all arguments must be picklable.

    Args:
        data: Raw chunk bytes.
        chunk_id: Index of the chunk, used for filenames.
        temp_dir: Directory to store intermediate files.

    Returns:
        Path to the compressed chunk archive.

    Raises:
        Exception: If compression of the chunk fails.
    """
    chunk_path = temp_dir / f"chunk_{chunk_id:06d}.bin"
    compressed_path = temp_dir / f"chunk_{chunk_id:06d}.7z"
    try:
        chunk_path.write_bytes(data)
        with py7zr.SevenZipFile(
            compressed_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
        ) as sevenz:
            sevenz.write(chunk_path, arcname=chunk_path.name)
        return compressed_path
    except Exception as e:  # noqa: BLE001
        raise Exception(f"Chunk {chunk_id} compression failed: {e}") from e
    finally:
        if chunk_path.exists():
            chunk_path.unlink()


def compress_chunked(in_path: Path, out_path: Path, file_size: int) -> bool:
    """Compress a large file by splitting it into chunks processed in parallel.

    Chunks are compressed using a multiprocessing pool and then combined
    into a single solid ``.7z`` archive.

    Args:
        in_path: Source file path.
        out_path: Destination ``.7z`` path.
        file_size: Size of the source file in bytes.

    Returns:
        True on success, False otherwise.
    """
    temp_dir = TEMP_DIR / f"compress_{in_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        chunk_count = (file_size + SMALL_FILE_THRESHOLD - 1) // SMALL_FILE_THRESHOLD
        compressed_paths: list[Path | None] = [None] * chunk_count
        pool = _get_pool()
        async_results = []
        with (
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            for i in range(chunk_count):
                start = i * SMALL_FILE_THRESHOLD
                end = min((i + 1) * SMALL_FILE_THRESHOLD, file_size)
                chunk = mm[start:end]
                async_results.append(
                    pool.apply_async(compress_chunk, (chunk, i, temp_dir))
                )
            for i, result in enumerate(async_results):
                try:
                    compressed_paths[i] = result.get()
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Chunk {i} compression failed: {e}")
                    return False
        with py7zr.SevenZipFile(
            out_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
        ) as sevenz:
            for compressed_path in compressed_paths:
                if compressed_path is not None and compressed_path.exists():
                    sevenz.write(compressed_path, arcname=compressed_path.name)
        return True
    except (OSError, MemoryError, py7zr.Bad7zFile) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


async def compress_folder_async(folder_path: Path, output_path: Path) -> bool:
    """Compress an entire folder into a single ``.7z`` archive asynchronously.

    Args:
        folder_path: Folder to compress.
        output_path: Destination ``.7z`` archive path.

    Returns:
        True if compression succeeded and saved space, False otherwise.
    """
    loop = asyncio.get_running_loop()

    def compress() -> None:
        """Synchronously write the folder archive (runs in executor)."""
        with py7zr.SevenZipFile(
            output_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
            recursive=True,
        ) as sevenz:
            sevenz.writeall(folder_path, arcname=folder_path.name)

    try:
        await loop.run_in_executor(None, compress)
        if not output_path.exists():
            return False
        original_size = sum(
            f.stat().st_size for f in folder_path.rglob("*") if f.is_file()
        )
        compressed_size = output_path.stat().st_size
        if compressed_size < original_size:
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            reduction = (original_size - compressed_size) / original_size * 100
            print(
                f"  ✓ Compressed archive: {reduction:.1f}% saved "
                f"({fsz(original_size)} → {fsz(compressed_size)})"
            )
            return True
        logger.warning("  ✗ Archive compression didn't save space")
        output_path.unlink()
        return False
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def compress_file(path: Path) -> tuple[bool, int, int]:
    """Compress a single file, choosing memory or chunked strategy by size.

    Args:
        path: Source file path.

    Returns:
        Tuple of ``(success, original_size, compressed_size)``. On failure
        or skip, sizes are 0.
    """
    out_path = path.with_suffix(path.suffix + ".7z")
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
            logger.warning(f"  ✗ {path.name}: No space saved, removing compressed file")
            out_path.unlink()
            return False, 0, 0
        return False, 0, 0
    except (OSError, PermissionError, py7zr.Bad7zFile) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


async def process_compress() -> None:
    """Compress all eligible files and directories in the current directory."""
    cwd = Path.cwd()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    print("\n🔧 7-Zip Compression Settings:")
    print("   Format: 7z")
    print("   Filter: LZMA2 (preset 9 - maximum)")
    print("   Dictionary size: 256 MB")
    print("   Solid compression: Yes")
    print("   Header compression: Yes")
    print("   Block size: 4 MB")
    print(f"   Parallel workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")

    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in dirs_to_compress:
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            output_path = dir_path.parent / f"{dir_path.name}.7z"
            if await compress_folder_async(dir_path, output_path):
                logger.success(
                    f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.7z"
                )
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")

    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return

    print(
        f"\n📄 Compressing {len(files_to_compress)} files with 7-Zip max compression..."
    )
    total_original = 0
    total_compressed = 0
    successful = 0
    for i, path in enumerate(files_to_compress, 1):
        print(f"\n[{i}/{len(files_to_compress)}] {path.name}")
        success, orig_size, comp_size = compress_file(path)
        if success:
            successful += 1
            total_original += orig_size
            total_compressed += comp_size

    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = savings / total_original * 100
        logger.success(f"\n{'=' * 40}")
        logger.success(f"✅ Compressed {successful}/{len(files_to_compress)} files")
        print(f"📊 Original size:  {fsz(total_original)}")
        print(f"📦 Compressed size: {fsz(total_compressed)}")
        print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
        logger.success(f"{'=' * 40}")
    elif files_to_compress:
        logger.error("\n❌ No files were successfully compressed")


async def process_decompress() -> None:
    """Decompress all ``.7z`` archives in the current directory."""
    cwd = Path.cwd()
    files_to_decompress = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .7z files to decompress")
        return

    print(f"\n📄 Decompressing {len(files_to_decompress)} 7-Zip archives...")
    total_original = 0
    total_decompressed = 0
    successful = 0
    for i, path in enumerate(files_to_decompress, 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        try:
            with py7zr.SevenZipFile(path, mode="r") as sevenz:
                out_path = path.with_suffix("")
                original_size = path.stat().st_size
                total_original += original_size
                if out_path.exists():
                    logger.warning("  Output already exists, skipping...")
                    continue
                sevenz.extractall(path=out_path)
                if out_path.is_file():
                    decompressed_size = out_path.stat().st_size
                else:
                    decompressed_size = sum(
                        f.stat().st_size for f in out_path.rglob("*") if f.is_file()
                    )
                total_decompressed += decompressed_size
                print(
                    f"  ✓ Decompressed {path.name}: "
                    f"{fsz(original_size)} → {fsz(decompressed_size)}"
                )
                path.unlink()
                successful += 1
        except Exception as e:  # noqa: BLE001
            logger.error(f"  ✗ Failed to decompress {path.name}: {e}")

    if successful > 0:
        logger.success(f"\n{'=' * 40}")
        logger.success(
            f"✅ Decompressed {successful}/{len(files_to_decompress)} archives"
        )
        print(f"📦 Compressed size:   {fsz(total_original)}")
        print(f"📊 Decompressed size: {fsz(total_decompressed)}")
        logger.success(f"{'=' * 40}")
    elif files_to_decompress:
        logger.error("\n❌ No files were successfully decompressed")


async def main_async(mode: str = "compress") -> None:
    """Dispatch to compress or decompress processing.

    Args:
        mode: Either ``"compress"`` or ``"decompress"``.
    """
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Multi-threaded 7-Zip compression/decompression tool (max compression)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
7-Zip Settings:
  - Format: 7z with LZMA2
  - Compression level: 9 (maximum)
  - Dictionary size: 256 MB
  - Solid compression: Enabled
  - Header compression: Enabled
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with 7-Zip (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .7z files",
    )
    return parser


def main() -> None:
    """CLI entry point for compression/decompression."""
    parser = _build_parser()
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
        _close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
