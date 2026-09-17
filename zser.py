#!/data/data/com.termux/files/home/.local/bin/python
"""zser - Modern parallel Zstandard compressor utility.

This script provides high-performance compression and decompression using
Zstandard algorithm with parallel processing capabilities. It can compress
individual files or entire directories into .tar.zst archives.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import shutil
import sys
import tarfile
from io import BytesIO
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Final, List

import zstandard as zstd

# Constants
ZST_EXT: Final[str] = ".zst"
SKIP_EXTS: Final[frozenset[str]] = frozenset(
    {
        ".xz",
        ".br",
        ".7z",
        ".zip",
        ".gz",
        ".bz2",
        ".zst",
        ".whl",
        ".mp4",
        ".mp3",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".webm",
    }
)
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
)
FIXED_WORKERS: Final[int] = 8  # Fixed number of workers
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger: logging.Logger = logging.getLogger(__name__)


def fsize(num: float) -> str:
    """Format file size in human-readable format.

    Args:
        num: Size in bytes

    Returns:
        Formatted string with appropriate unit (B, KB, MB, GB, TB)
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def get_dir_size(path: Path) -> int:
    """Calculate total size of all files in directory recursively.

    Args:
        path: Directory path to calculate size for

    Returns:
        Total size in bytes
    """
    total: int = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except Exception:
        pass
    return total


def compress_file(path: Path, level: int = 21) -> dict[str, Any]:
    """Compress a single file using Zstandard compression.

    Args:
        path: File path to compress
        level: Compression level (1-22, default: 21)

    Returns:
        Dictionary containing compression results with status, sizes, and errors
    """
    dst: Path = path.with_suffix(path.suffix + ZST_EXT)
    if dst.exists():
        return {"status": "skip", "path": str(path)}
    try:
        size: int = path.stat().st_size
        if size == 0:
            path.unlink()
            return {"status": "skip", "path": str(path), "reason": "empty"}

        cctx: zstd.ZstdCompressor = zstd.ZstdCompressor(
            level=level, write_content_size=True
        )
        data: bytes = path.read_bytes()
        compressed: bytes = cctx.compress(data)
        dst.write_bytes(compressed)
        path.unlink()

        return {
            "status": "ok",
            "path": str(path),
            "original": size,
            "compressed": len(compressed),
        }
    except Exception as e:
        dst.unlink(missing_ok=True)
        return {"status": "error", "path": str(path), "error": str(e)}


def decompress_file(path: Path) -> dict[str, Any]:
    """Decompress a Zstandard compressed file.

    Args:
        path: Path to .zst file to decompress

    Returns:
        Dictionary containing decompression results with status and sizes
    """
    if path.suffix != ZST_EXT:
        return {"status": "skip", "path": str(path)}

    dst: Path = path.with_suffix("")
    if dst.exists():
        return {"status": "skip", "path": str(path)}

    try:
        dctx: zstd.ZstdDecompressor = zstd.ZstdDecompressor()
        data: bytes = path.read_bytes()
        decompressed: bytes = dctx.decompress(data)
        dst.write_bytes(decompressed)

        if dst.suffix == ".tar":
            try:
                with tarfile.open(dst, "r") as tar:
                    tar.extractall(path=dst.parent)
                dst.unlink()
                path.unlink()
                return {
                    "status": "ok",
                    "path": str(path),
                    "extracted": True,
                    "original": len(data),
                    "decompressed": len(decompressed),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "path": str(path),
                    "error": f"tar extract: {e}",
                }

        path.unlink()
        return {
            "status": "ok",
            "path": str(path),
            "dst": str(dst),
            "original": len(data),
            "decompressed": len(decompressed),
        }
    except Exception as e:
        dst.unlink(missing_ok=True)
        return {"status": "error", "path": str(path), "error": str(e)}


def compress_dir(path: Path, level: int = 21) -> dict[str, Any]:
    """Compress an entire directory into a tar.zst archive.

    Args:
        path: Directory path to compress
        level: Compression level (1-22, default: 21)

    Returns:
        Dictionary containing compression results with status and sizes
    """
    zst_path: Path = path.with_name(f"{path.name}.tar{ZST_EXT}")
    try:
        buf: BytesIO = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(path, arcname=path.name)

        tar_data: bytes = buf.getvalue()
        cctx: zstd.ZstdCompressor = zstd.ZstdCompressor(
            level=level, write_content_size=True
        )
        compressed: bytes = cctx.compress(tar_data)
        orig_size: int = get_dir_size(path)

        zst_path.write_bytes(compressed)
        shutil.rmtree(path)

        return {
            "status": "ok",
            "path": str(path),
            "original": orig_size,
            "compressed": len(compressed),
        }
    except Exception as e:
        zst_path.unlink(missing_ok=True)
        return {"status": "error", "path": str(path), "error": str(e)}


def process_files_async(files: list[Path], operation: str, level: int = 21) -> None:
    """Process multiple files in parallel using multiprocessing pool.

    Args:
        files: List of file paths to process
        operation: Operation type ("compress" or "decompress")
        level: Compression level (for compression only, default: 21)
    """
    with Pool(processes=FIXED_WORKERS) as pool:
        async_results: list[AsyncResult] = []

        # Submit all tasks
        for path in files:
            if operation == "compress":
                async_result: AsyncResult = pool.apply_async(
                    compress_file, (path, level)
                )
            else:  # decompress
                async_result = pool.apply_async(decompress_file, (path,))
            async_results.append(async_result)

        # Collect and process results
        for async_result in async_results:
            try:
                res: dict[str, Any] = async_result.get(timeout=300)  # 5 minute timeout
                if res["status"] == "ok":
                    if operation == "compress":
                        print(
                            f"  ✓ {Path(res['path']).name}: "
                            f"{fsize(res['original'])} → {fsize(res['compressed'])}"
                        )
                    else:  # decompress
                        print(f"  ✓ {Path(res['path']).name}")
                elif res["status"] == "error":
                    logger.error(
                        f"  ✗ {res['path']}: {res.get('error', 'Unknown error')}"
                    )
            except Exception as e:
                logger.error(f"  ✗ Failed to process task: {e}")


def main() -> int:
    """Main entry point for zser utility.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="zser – modern parallel Zstandard compressor"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", default=True)
    group.add_argument("-d", "--decompress", action="store_true")
    parser.add_argument(
        "-l", "--level", type=int, default=21, help="Compression level (1-22)"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=FIXED_WORKERS,
        help=f"Number of workers (fixed at {FIXED_WORKERS})",
    )
    parser.add_argument("-p", "--path", type=Path, default=Path.cwd())
    parser.add_argument("--no-dirs", action="store_true")

    args: argparse.Namespace = parser.parse_args()
    target: Path = args.path.resolve()

    if not target.is_dir():
        logger.error("Target must be a directory")
        return 1

    initial_size: int = get_dir_size(target)
    mode: str = "decompress" if args.decompress else "compress"

    print(
        f"zser - {mode} | {target} | workers={FIXED_WORKERS} | "
        f"size={fsize(initial_size)}"
    )

    if args.decompress:
        files: list[Path] = list(target.glob(f"*{ZST_EXT}"))
        if not files:
            print("No .zst files found")
            return 0
        process_files_async(files, "decompress")
    else:
        # Process directories first (sequential)
        if not args.no_dirs:
            dirs: list[Path] = [
                p for p in target.iterdir() if p.is_dir() and p.name not in SKIP_DIRS
            ]
            for d in dirs:
                print(f"  dir  {d.name}...")
                res: dict[str, Any] = compress_dir(d, args.level)
                if res["status"] == "ok":
                    print(
                        f"    ✓ {fsize(res['original'])} → {fsize(res['compressed'])}"
                    )
                elif res["status"] == "error":
                    logger.error(f"    ✗ {res.get('error', 'Unknown error')}")

        # Process files in parallel
        files: list[Path] = [
            p for p in target.iterdir() if p.is_file() and p.suffix not in SKIP_EXTS
        ]
        if files:
            process_files_async(files, "compress", args.level)
        else:
            print("Nothing to compress")

    final_size: int = get_dir_size(target)
    print(
        f"\nFinal size: {fsize(final_size)} (saved {fsize(initial_size - final_size)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
