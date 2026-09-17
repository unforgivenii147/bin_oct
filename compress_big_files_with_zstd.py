#!/data/data/com.termux/files/home/.local/bin/python
"""
Compress large files in the current directory tree using zstd, with a multiprocessing pool.

Prompt to regenerate: Write a Python CLI that takes a byte threshold, recursively finds files
in the current directory larger than that threshold, skips already-compressed/media extensions,
compresses eligible files in-place with zstandard (only keeping the result if it is smaller),
removes the originals, shows a live progress bar with loguru logging, and runs compression
across a fixed multiprocessing.Pool of 8 workers with full type hints and docstrings.
"""

from __future__ import annotations

import sys
import threading
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Final

import zstandard as zstd
from loguru import logger

GREEN: Final[str] = "\x1b[92m"
YELLOW: Final[str] = "\x1b[93m"
BLUE: Final[str] = "\x1b[94m"
RED: Final[str] = "\x1b[91m"
RESET: Final[str] = "\x1b[0m"

POOL_WORKERS: Final[int] = 8
ZSTD_THREADS: Final[int] = 4
DEFAULT_LEVEL: Final[int] = 3

COMPRESSED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".zst",
        ".gz",
        ".bz2",
        ".xz",
        ".zip",
        ".rar",
        ".7z",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".mp4",
        ".avi",
        ".mkv",
        ".mp3",
        ".flac",
        ".pdf",
    }
)

# Shared progress state for worker processes (fork-friendly on POSIX).
_progress_lock: threading.Lock = threading.Lock()
_total_files: int = 0
_processed_files: int = 0
_total_size: int = 0
_compressed_size: int = 0
_start_time: float = time.time()


class ProgressDisplay:
    """Thread-safe progress reporter for compression results."""

    def __init__(self) -> None:
        """Initialize counters and timing state."""
        self.lock: threading.Lock = threading.Lock()
        self.total_files: int = 0
        self.processed_files: int = 0
        self.total_size: int = 0
        self.compressed_size: int = 0
        self.start_time: float = time.time()

    def set_total_files(self, count: int) -> None:
        """Set the total number of files expected to be processed."""
        self.total_files = count

    def update(
        self,
        path: Path,
        original_size: int,
        compressed_size: int,
        status: str = "compressed",
    ) -> None:
        """Record a file result and render the progress bar."""
        with self.lock:
            self.processed_files += 1
            self.total_size += original_size
            self.compressed_size += compressed_size
            elapsed = time.time() - self.start_time
            if self.total_files > 0:
                percent = self.processed_files / self.total_files * 100.0
            else:
                percent = 0.0
            if self.total_size > 0:
                ratio = self.compressed_size / self.total_size
                savings = (1.0 - ratio) * 100.0
            else:
                savings = 0.0
            if elapsed > 0:
                speed = self.total_size / (1024 * 1024) / elapsed
            else:
                speed = 0.0
            bar_length = 30
            filled = int(bar_length * percent / 100.0)
            filled = max(0, min(filled, bar_length - 1))
            bar = "=" * filled + ">" + "." * (bar_length - filled - 1)
            status_color = GREEN if status == "compressed" else YELLOW
            filename = path.name
            if len(filename) > 30:
                filename = filename[:27] + "..."
            sys.stdout.write(
                f"\r{status_color}{status.upper():10}{RESET} [{bar}] "
                f"{percent:5.1f}% {self.processed_files}/{self.total_files} files "
                f"({savings:5.1f}% saved, {speed:5.1f} MB/s) - {filename:<30}"
            )
            sys.stdout.flush()

    def finish(self) -> None:
        """Log a final summary of the compression run."""
        elapsed = time.time() - self.start_time
        sys.stdout.write("\n")
        sys.stdout.flush()
        logger.success("Compression complete!")
        print("Files processed: {}/{}", self.processed_files, self.total_files)
        if self.total_size > 0:
            orig_mb = self.total_size / (1024 * 1024)
            comp_mb = self.compressed_size / (1024 * 1024)
            savings = (1.0 - self.compressed_size / self.total_size) * 100.0
            print("Original size: {:.2f} MB", orig_mb)
            print("Compressed size: {:.2f} MB", comp_mb)
            print("Savings: {:.1f}%", savings)
            print("Time: {:.1f} seconds", elapsed)
            if elapsed > 0:
                print(
                    "Average speed: {:.1f} MB/s",
                    self.total_size / (1024 * 1024) / elapsed,
                )


def should_compress_file(path: Path, threshold: int) -> bool:
    """Return True if the file is eligible for compression."""
    if path.suffix.lower() in COMPRESSED_EXTENSIONS:
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return size > threshold


def compress_file(
    path: Path,
    progress: ProgressDisplay,
    level: int = DEFAULT_LEVEL,
) -> tuple[bool, Path, Path | None, int]:
    """Compress a single file, replacing it if the result is smaller."""
    original_size = path.stat().st_size
    compressed_path = path.with_suffix(path.suffix + ".zst")
    temp_path = path.with_suffix(path.suffix + ".zst.tmp")
    try:
        cctx = zstd.ZstdCompressor(level=level, threads=ZSTD_THREADS)
        with open(path, "rb") as f_in:
            data = f_in.read()
        compressed_data = cctx.compress(data)
        compressed_size = len(compressed_data)
        if compressed_size < original_size:
            with open(temp_path, "wb") as f_out:
                f_out.write(compressed_data)
            temp_path.rename(compressed_path)
            path.unlink()
            progress.update(path, original_size, compressed_size, "compressed")
            return True, path, compressed_path, compressed_size
        progress.update(path, original_size, original_size, "skipped")
        return False, path, None, original_size
    except Exception as exc:  # noqa: BLE001 - surfaced via progress
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        progress.update(
            path,
            original_size,
            original_size,
            f"error: {str(exc)[:20]}",
        )
        return False, path, None, original_size


def _worker(args: tuple[Path, int]) -> tuple[bool, Path, Path | None, int]:
    """Multiprocessing entry point that updates the shared progress state."""
    path, level = args
    original_size = path.stat().st_size
    compressed_path = path.with_suffix(path.suffix + ".zst")
    temp_path = path.with_suffix(path.suffix + ".zst.tmp")
    try:
        cctx = zstd.ZstdCompressor(level=level, threads=ZSTD_THREADS)
        with open(path, "rb") as f_in:
            data = f_in.read()
        compressed_data = cctx.compress(data)
        compressed_size = len(compressed_data)
        if compressed_size < original_size:
            with open(temp_path, "wb") as f_out:
                f_out.write(compressed_data)
            temp_path.rename(compressed_path)
            path.unlink()
            _record(path, original_size, compressed_size, "compressed")
            return True, path, compressed_path, compressed_size
        _record(path, original_size, original_size, "skipped")
        return False, path, None, original_size
    except Exception as exc:  # noqa: BLE001 - surfaced via progress
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        _record(path, original_size, original_size, f"error: {str(exc)[:20]}")
        return False, path, None, original_size


def _record(
    path: Path,
    original_size: int,
    compressed_size: int,
    status: str,
) -> None:
    """Update shared progress counters and emit a progress line."""
    global _processed_files, _total_size, _compressed_size
    with _progress_lock:
        _processed_files += 1
        _total_size += original_size
        _compressed_size += compressed_size
        processed = _processed_files
        total = _total_files
        total_size = _total_size
        compressed = _compressed_size
        start = _start_time
    elapsed = time.time() - start
    percent = processed / total * 100.0 if total > 0 else 0.0
    if total_size > 0:
        savings = (1.0 - compressed / total_size) * 100.0
    else:
        savings = 0.0
    speed = total_size / (1024 * 1024) / elapsed if elapsed > 0 else 0.0
    bar_length = 30
    filled = max(0, min(int(bar_length * percent / 100.0), bar_length - 1))
    bar = "=" * filled + ">" + "." * (bar_length - filled - 1)
    status_color = GREEN if status == "compressed" else YELLOW
    filename = path.name
    if len(filename) > 30:
        filename = filename[:27] + "..."
    sys.stdout.write(
        f"\r{status_color}{status.upper():10}{RESET} [{bar}] "
        f"{percent:5.1f}% {processed}/{total} files "
        f"({savings:5.1f}% saved, {speed:5.1f} MB/s) - {filename:<30}"
    )
    sys.stdout.flush()


def _format_threshold(threshold: int) -> str:
    """Return a human-readable representation of a byte threshold."""
    if threshold >= 1024 * 1024 * 1024:
        return f"{threshold / (1024 * 1024 * 1024):.1f} GB"
    if threshold >= 1024 * 1024:
        return f"{threshold / (1024 * 1024):.1f} MB"
    if threshold >= 1024:
        return f"{threshold / 1024:.1f} KB"
    return f"{threshold} bytes"


def _collect_files(current_dir: Path, threshold: int) -> list[Path]:
    """Recursively collect files larger than the threshold."""
    return [
        p
        for p in current_dir.rglob("*")
        if p.is_file() and should_compress_file(p, threshold)
    ]


def main() -> int:
    """Entry point: parse the threshold, scan, and compress eligible files."""
    global _total_files, _start_time

    if len(sys.argv) != 2:
        logger.error("Usage: python {} <threshold_in_bytes>", sys.argv[0])
        print("Example: python {} 1048576  # > 1MB", sys.argv[0])
        print("Example: python {} 5242880  # > 5MB", sys.argv[0])
        return 1

    try:
        threshold = int(sys.argv[1])
    except ValueError:
        logger.error("Invalid threshold. Please provide a number in bytes.")
        return 1

    if threshold <= 0:
        logger.error("Threshold must be positive")
        return 1

    threshold_str = _format_threshold(threshold)
    print("Compressing files larger than {}", threshold_str)
    print("Scanning current directory...")

    current_dir = Path.cwd()
    files_to_compress = _collect_files(current_dir, threshold)

    if not files_to_compress:
        logger.warning("No files found larger than {}", threshold_str)
        return 0

    logger.success("Found {} files to compress", len(files_to_compress))

    _total_files = len(files_to_compress)
    _start_time = time.time()

    total_original = 0
    total_compressed = 0
    processed = 0

    try:
        with Pool(processes=POOL_WORKERS) as pool:
            async_results = [
                pool.apply_async(_worker, ((f, DEFAULT_LEVEL),))
                for f in files_to_compress
            ]
            for result in async_results:
                try:
                    _ok, path, comp_path, size = result.get()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error processing file: {}", exc)
                    continue
                processed += 1
                if comp_path is not None:
                    total_original += path.stat().st_size if path.exists() else 0
                    total_compressed += size
                if processed == len(files_to_compress):
                    break
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130

    sys.stdout.write("\n")
    sys.stdout.flush()
    logger.success("Compression complete!")
    print("Files processed: {}/{}", processed, len(files_to_compress))
    elapsed = time.time() - _start_time
    print("Time: {:.1f} seconds", elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
