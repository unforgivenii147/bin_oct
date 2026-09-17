#!/data/data/com.termux/files/home/.local/bin/python
"""Parallel Zstandard compression and decompression tool.

This module provides a command-line interface for recursively compressing
and decompressing files using the Zstandard algorithm. It supports
parallel processing across multiple CPU cores and optional tar archiving
of subdirectories before compression.

Key features:
    - Recursive directory traversal with configurable skip patterns
    - Parallel file processing using multiprocessing
    - Optional tar-before-compress for subdirectories
    - Adaptive compression levels based on file size
    - Dry-run mode for previewing operations
    - Progress reporting with compression ratios

Example:
    $ python zstder.py --compress /path/to/directory
    $ python zstder.py --decompress --verbose /path/to/directory
    $ python zstder.py --tar-subdirs-first --dry-run /path/to/directory
"""

from __future__ import annotations

import argparse
import shutil
import tarfile
import threading
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

import zstandard as zstd
from dh import fsz
from loguru import logger

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

# File size threshold for adaptive compression level selection
LARGE_FILE_THRESHOLD: Final[int] = 5 * 1024 * 1024

# Compression levels
LEVEL_DEFAULT: Final[int] = 21
LEVEL_LARGE: Final[int] = 21

# File extension for compressed files
ZSTD_EXT: Final[str] = ".zst"

# Default number of threads for zstd compression
DEFAULT_THREADS: Final[int] = 4

# Fixed number of worker processes for parallel processing
WORKERS: Final[int] = 8


def choose_level(path: Path) -> int:
    """Select appropriate compression level based on file size.

    Args:
        path: Path to the file being compressed.

    Returns:
        Compression level (9 for large files, 19 for regular files).
    """
    try:
        return (
            LEVEL_LARGE if path.stat().st_size > LARGE_FILE_THRESHOLD else LEVEL_DEFAULT
        )
    except OSError:
        return LEVEL_DEFAULT


def ratio_str(before: int, after: int) -> str:
    """Calculate and format compression ratio as percentage.

    Args:
        before: Original file size in bytes.
        after: Compressed file size in bytes.

    Returns:
        Formatted string showing compression ratio percentage.
    """
    if before == 0:
        return "0%"
    return f"{after / before * 40:.1f}%"


def status_line(ok: bool, name: str, elapsed_ms: float, before: int, after: int) -> str:
    """Format a status line for display.

    Args:
        ok: Whether the operation succeeded.
        name: Name of the file being processed.
        elapsed_ms: Time taken for the operation in milliseconds.
        before: Original file size in bytes.
        after: Processed file size in bytes.

    Returns:
        Formatted status line string.
    """
    icon = "✔" if ok else "✘"
    return f"[{icon}] {name} ({elapsed_ms:.0f}ms) {ratio_str(before, after)}"


def compress_file(
    src: Path, dry_run: bool, verbose: bool, level: int = 21, threads: int = 4
) -> dict[str, Any]:
    """Compress a single file using Zstandard.

    Args:
        src: Path to the file to compress.
        dry_run: If True, don't actually compress the file.
        verbose: If True, include additional details in result.
        level: Compression level (default: 21).
        threads: Number of threads for compression (default: 4).

    Returns:
        Dictionary containing result status and formatted messages.
    """
    result: dict[str, Any] = {"src": src, "ok": False, "line": "", "msg": ""}
    dst: Path = src.with_suffix(src.suffix + ZSTD_EXT)

    if dst.exists():
        result["line"] = f"[–] {src.name} (skipped — {dst.name} exists)"
        return result

    effective_level: int = level if level is not None else choose_level(src)

    if dry_run:
        result["ok"] = True
        result["line"] = (
            f"[dry-run] {src.name} → {dst.name} (level {effective_level}, threads {threads})"
        )
        return result

    t0: float = time.perf_counter()
    try:
        cctx: zstd.ZstdCompressor = zstd.ZstdCompressor(
            level=effective_level, threads=threads
        )
        data: bytes = src.read_bytes()
        compressed: bytes = cctx.compress(data)
        dst.write_bytes(compressed)
        elapsed_ms: float = (time.perf_counter() - t0) * 400
        after: int = len(compressed)
        before: int = len(data)
        src.unlink()
        result["ok"] = True
        result["line"] = status_line(True, src.name, elapsed_ms, before, after)
        if verbose:
            result["msg"] = (
                f"  → {dst.name} ({fsz(before)} → {fsz(after)}, level {effective_level}, {threads} threads)"
            )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 400
        result["line"] = status_line(False, src.name, elapsed_ms, 0, 0)
        result["msg"] = f"  ERROR: {exc}"

    return result


def decompress_file(src: Path, dry_run: bool, verbose: bool) -> dict[str, Any]:
    """Decompress a single Zstandard file.

    Args:
        src: Path to the compressed file.
        dry_run: If True, don't actually decompress the file.
        verbose: If True, include additional details in result.

    Returns:
        Dictionary containing result status and formatted messages.
    """
    result: dict[str, Any] = {"src": src, "ok": False, "line": "", "msg": ""}

    if src.suffix != ZSTD_EXT:
        result["line"] = f"[–] {src.name} (skipped — not a {ZSTD_EXT} file)"
        return result

    dst: Path = src.with_suffix("")

    if dst.exists():
        result["line"] = f"[–] {src.name} (skipped — {dst.name} exists)"
        return result

    if dry_run:
        result["ok"] = True
        result["line"] = f"[dry-run] {src.name} → {dst.name}"
        return result

    t0: float = time.perf_counter()
    try:
        dctx: zstd.ZstdDecompressor = zstd.ZstdDecompressor()
        data: bytes = src.read_bytes()
        decompressed: bytes = dctx.decompress(data)
        dst.write_bytes(decompressed)
        elapsed_ms: float = (time.perf_counter() - t0) * 400
        after: int = len(decompressed)
        before: int = len(data)
        src.unlink()
        result["ok"] = True
        result["line"] = status_line(True, src.name, elapsed_ms, before, after)
        if verbose:
            result["msg"] = f"  → {dst.name} ({fsz(before)} → {fsz(after)})"
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 400
        result["line"] = status_line(False, src.name, elapsed_ms, 0, 0)
        result["msg"] = f"  ERROR: {exc}"

    return result


def tar_subdir(subdir: Path, dry_run: bool, verbose: bool) -> Path | None:
    """Create a tar archive of a subdirectory.

    Args:
        subdir: Path to the subdirectory to archive.
        dry_run: If True, don't actually create the archive.
        verbose: If True, log additional details.

    Returns:
        Path to the created tar file, or None if creation failed.
    """
    tar_path: Path = subdir.parent / f"{subdir.name}.tar"

    if dry_run:
        if verbose:
            print(f"  [dry-run] would tar {subdir}/ → {tar_path.name}")
        return tar_path

    try:
        with tarfile.open(tar_path, "w") as tf:
            tf.add(subdir, arcname=subdir.name)
        if verbose:
            print(
                f"  tarred {subdir.name}/ → {tar_path.name} ({fsz(tar_path.stat().st_size)})"
            )
        return tar_path
    except Exception as exc:
        logger.error(f"  ERROR tarring {subdir}: {exc}")
        return None


def remove_subdir(subdir: Path, dry_run: bool, verbose: bool) -> None:
    """Remove a subdirectory after successful compression.

    Args:
        subdir: Path to the subdirectory to remove.
        dry_run: If True, don't actually remove the directory.
        verbose: If True, log additional details.
    """
    if dry_run:
        print(f"  [dry-run] would remove {subdir}/")
        return

    try:
        shutil.rmtree(subdir)
        print(f"  removed original dir: {subdir.name}/")
    except Exception as exc:
        logger.warning(f"  WARNING — could not remove {subdir}: {exc}")


def run_parallel(
    tasks: list[Path], worker_fn: Any, extra_kwargs: dict[str, Any]
) -> tuple[int, int]:
    """Execute tasks in parallel using multiprocessing pool.

    Args:
        tasks: List of paths to process.
        worker_fn: Function to execute on each task.
        extra_kwargs: Additional keyword arguments for the worker function.

    Returns:
        Tuple of (successful_count, error_count).
    """
    results: list[dict[str, Any]] = []
    lock: threading.Lock = threading.Lock()

    def callback(res: dict[str, Any]) -> None:
        """Callback function for completed tasks.

        Args:
            res: Result dictionary from worker function.
        """
        nonlocal results
        with lock:
            results.append(res)
            print(res["line"])
            if res.get("msg"):
                if res["ok"]:
                    print(res["msg"])
                else:
                    logger.error(res["msg"])

    pool = Pool(processes=WORKERS)
    print(type(pool))
    input("press any key to continue...")
    try:
        for path in tasks:
            pool.apply_async(
                worker_fn,
                args=(path,),
                kwds=extra_kwargs,
                callback=callback,
            )
        pool.close()
        pool.join()
    finally:
        pool.terminate()  # Ensure clean-up if something goes wrong

    ok: int = sum(1 for r in results if r["ok"])
    err: int = sum(1 for r in results if not r["ok"])
    return (ok, err)


def do_compress(
    root: Path, tar_subdirs: bool, dry_run: bool, verbose: bool, threads: int
) -> None:
    """Compress files in a directory tree.

    Args:
        root: Root directory to process.
        tar_subdirs: If True, tar subdirectories before compressing.
        dry_run: If True, don't actually compress files.
        verbose: If True, log additional details.
        threads: Number of threads for zstd compression.
    """
    start: float = time.perf_counter()

    if tar_subdirs:
        subdirs: list[Path] = [
            p for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS
        ]
        if verbose:
            print(f"Tarring {len(subdirs)} subdirectory/ies …")

        tar_paths: list[tuple[Path, Path | None]] = []
        for sd in subdirs:
            tp: Path | None = tar_subdir(sd, dry_run, verbose)
            if tp:
                tar_paths.append((sd, tp))

        tar_files: list[Path] = [tp for _, tp in tar_paths if tp is not None]

        if tar_files:
            if verbose:
                print(
                    f"Compressing {len(tar_files)} .tar archive(s) at level {LEVEL_LARGE} …"
                )
            run_parallel(
                tar_files,
                compress_file,
                {
                    "dry_run": dry_run,
                    "verbose": verbose,
                    "level": LEVEL_LARGE,
                    "threads": threads,
                },
            )

            compressed: set[Path] = {
                tp
                for tp in tar_files
                if tp.with_suffix(tp.suffix + ZSTD_EXT).exists() or dry_run
            }
            for sd, tp in tar_paths:
                if tp is not None and tp in compressed:
                    remove_subdir(sd, dry_run, verbose)

        loose: list[Path] = [
            p for p in root.iterdir() if p.is_file() and p.suffix != ZSTD_EXT
        ]
        if loose:
            if verbose:
                print(f"Compressing {len(loose)} loose file(s) …")
            run_parallel(
                loose,
                compress_file,
                {"dry_run": dry_run, "verbose": verbose, "threads": threads},
            )
    else:
        files: list[Path] = [
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix != ZSTD_EXT
            and (not any(part in SKIP_DIRS for part in p.parts))
        ]

        if not files:
            print("No files to compress.")
            return

        if verbose:
            print(
                f"Compressing {len(files)} file(s) with {WORKERS} processes × {threads} zstd threads each …"
            )

        ok: int
        err: int
        ok, err = run_parallel(
            files,
            compress_file,
            {"dry_run": dry_run, "verbose": verbose, "threads": threads},
        )

        elapsed: float = time.perf_counter() - start
        print(f"\nDone — {ok} compressed, {err} error(s) [{elapsed:.2f}s]")
        return

    elapsed = time.perf_counter() - start
    print(f"\nDone [{elapsed:.2f}s]")


def do_decompress(root: Path, dry_run: bool, verbose: bool) -> None:
    """Decompress files in a directory tree.

    Args:
        root: Root directory to process.
        dry_run: If True, don't actually decompress files.
        verbose: If True, log additional details.
    """
    start: float = time.perf_counter()
    files: list[Path] = [p for p in root.rglob(f"*{ZSTD_EXT}") if p.is_file()]

    if not files:
        print(f"No {ZSTD_EXT} files found.")
        return

    if verbose:
        print(f"Decompressing {len(files)} file(s) with {WORKERS} workers …")

    ok: int
    err: int
    ok, err = run_parallel(
        files, decompress_file, {"dry_run": dry_run, "verbose": verbose}
    )

    elapsed: float = time.perf_counter() - start
    print(f"\nDone — {ok} decompressed, {err} error(s) [{elapsed:.2f}s]")


def main() -> None:
    """Parse command-line arguments and execute the requested operation."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="zstder",
        description="Recursive Zstandard compression/decompression tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode: argparse._MutuallyExclusiveGroup = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-c", "--compress", action="store_true", help="Compress files (default)"
    )
    mode.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress files"
    )
    parser.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        help="Tar subdirs before compressing.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"zstd intra-file compression threads (default: {DEFAULT_THREADS}).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="Do not modify files"
    )
    parser.add_argument(
        "directory", nargs="?", default=".", help="Root directory (default: current)"
    )

    args: argparse.Namespace = parser.parse_args()
    root: Path = Path(args.directory).resolve()

    if not root.is_dir():
        parser.error(f"Not a directory: {root}")

    compress: bool = args.compress or not args.decompress

    if args.dry_run:
        print("[dry-run mode — no files will be modified]")
    if args.verbose or args.dry_run:
        print(f"Root    : {root}")
        print(f"Mode    : {('compress' if compress else 'decompress')}")
        print(f"Threads : {args.threads} (zstd) × {WORKERS} processes")
        print()

    if compress:
        do_compress(
            root, args.tar_subdirs_first, args.dry_run, args.verbose, args.threads
        )
    else:
        if args.tar_subdirs_first:
            logger.warning("Note: --tar-subdirs-first ignored during decompression.")
        do_decompress(root, args.dry_run, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
