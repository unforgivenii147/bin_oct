#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI tool that compresses and decompresses files using Zstandard with parallel multiprocessing, rich progress reporting, loguru logging, pathlib paths, tar auto-extraction, and a summary table.
"""

from __future__ import annotations

import argparse
import tarfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import zstandard as zstd
from dh import fsz, should_skip
from loguru import logger

EXCLUDED_EXTENSIONS: set[str] = {
    ".xz",
    ".zst",
    ".zstd",
    ".7z",
    ".gz",
    ".bz2",
    ".zip",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz2",
    ".txz",
    ".tlz",
    ".lz",
    ".lz4",
    ".lzma",
    ".lzo",
    ".sz",
    ".snappy",
    ".zlib",
    ".deflate",
    ".flac",
    ".mp3",
    ".aac",
    ".ogg",
    ".wma",
    ".opus",
    ".m4a",
    ".wavpack",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".wasm",
    ".whl",
    ".egg",
    ".deb",
    ".rpm",
    ".apk",
    ".ipa",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
    ".lib",
    ".a",
    ".iso",
    ".img",
    ".dmg",
    ".vdi",
    ".vmdk",
    ".qcow2",
}

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE: bool = True
except ImportError:
    RICH_AVAILABLE = False

POOL_SIZE: int = 8
CHUNK_SIZE: int = 1024 * 1024
MAX_SUMMARY_ROWS: int = 15


@dataclass(slots=True)
class OperationResult:
    """Result of a compress or decompress operation for one file."""

    path: Path
    original_size: int
    processed_size: int
    success: bool
    duration: float = 0.0
    original_deleted: bool = False
    operation: str = "compress"
    was_tarred: bool = False
    was_untarred: bool = False
    error: str | None = None

    @property
    def ratio(self) -> float:
        """Percentage-style space savings (compress) or growth (decompress)."""
        if self.original_size == 0:
            return 0.0
        if self.operation == "compress":
            return (1 - self.processed_size / self.original_size) * 40
        return (self.processed_size / self.original_size - 1) * 40


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int = 19,
    threads: int = 4,
    chunk_size: int = CHUNK_SIZE,
    keep_original: bool = False,
    was_tarred: bool = False,
) -> OperationResult:
    """Compress a single file with Zstandard, optionally deleting the original."""
    start_time = time.perf_counter()
    try:
        orig_size = input_path.stat().st_size
        if orig_size == 0:
            return OperationResult(
                path=input_path,
                original_size=0,
                processed_size=0,
                success=False,
                operation="compress",
                error="Empty file",
            )
        cctx = zstd.ZstdCompressor(level=level, threads=threads)
        with (
            input_path.open("rb") as f_in,
            output_path.open("wb") as f_out,
            cctx.stream_writer(f_out) as compressor,
        ):
            while chunk := f_in.read(chunk_size):
                compressor.write(chunk)
        proc_size = output_path.stat().st_size
        deleted = False
        if not keep_original:
            input_path.unlink()
            deleted = True
        return OperationResult(
            path=input_path,
            original_size=orig_size,
            processed_size=proc_size,
            success=True,
            duration=time.perf_counter() - start_time,
            original_deleted=deleted,
            operation="compress",
            was_tarred=was_tarred,
        )
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            output_path.unlink()
        return OperationResult(
            path=input_path,
            original_size=0,
            processed_size=0,
            success=False,
            duration=time.perf_counter() - start_time,
            operation="compress",
            was_tarred=was_tarred,
            error=str(e),
        )


def decompress_file(
    input_path: Path,
    output_path: Path,
    chunk_size: int = CHUNK_SIZE,
    keep_original: bool = False,
    auto_untar: bool = True,
) -> OperationResult:
    """Decompress a single Zstandard file, optionally auto-extracting tar contents."""
    start_time = time.perf_counter()
    try:
        orig_size = input_path.stat().st_size
        dctx = zstd.ZstdDecompressor()
        with (
            input_path.open("rb") as f_in,
            output_path.open("wb") as f_out,
            dctx.stream_reader(f_in) as decompressor,
        ):
            while chunk := decompressor.read(chunk_size):
                f_out.write(chunk)
        proc_size = output_path.stat().st_size
        was_untarred = False
        if auto_untar and output_path.suffix == ".tar":
            try:
                with tarfile.open(output_path, "r") as tar:
                    tar.extractall(output_path.parent, filter="data")
                output_path.unlink()
                was_untarred = True
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"Tar extraction failed: {e}") from e
        deleted = False
        if not keep_original:
            input_path.unlink()
            deleted = True
        return OperationResult(
            path=input_path,
            original_size=orig_size,
            processed_size=proc_size,
            success=True,
            duration=time.perf_counter() - start_time,
            original_deleted=deleted,
            operation="decompress",
            was_untarred=was_untarred,
        )
    except Exception as e:  # noqa: BLE001
        if output_path.exists():
            output_path.unlink()
        return OperationResult(
            path=input_path,
            original_size=0,
            processed_size=0,
            success=False,
            duration=time.perf_counter() - start_time,
            operation="decompress",
            error=str(e),
        )


def _walk_files(root_dir: Path) -> Iterable[Path]:
    """Yield files under root_dir using the fastwalk walker."""
    from fastwalk import walk_files

    yield from walk_files(root_dir)


def get_files(
    root: Path,
    mode: str,
    exclude_ext: set[str],
    exclude_patterns: list[str],
    ext_filter: list[str] | None = None,
    recursive: bool = True,
) -> list[Path]:
    """Collect candidate files for the given mode, applying filters."""
    found: list[Path] = []
    for p in _walk_files(root):
        if should_skip(p):
            continue
        if exclude_patterns and any(pat in str(p) for pat in exclude_patterns):
            continue
        if mode == "compress":
            if p.suffix.lower() in exclude_ext:
                continue
            if ext_filter:
                normalized_filter = [
                    f if f.startswith(".") else f".{f}" for f in ext_filter
                ]
                if p.suffix.lower() not in normalized_filter:
                    continue
            found.append(p)
        elif p.suffix.lower() == ".zst":
            found.append(p)
    _ = recursive  # reserved for future use
    return sorted(found)


def print_summary(results: list[OperationResult], root: Path, operation: str) -> None:
    """Print a rich (or plain) summary table and totals for the operation."""
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    total_orig = sum(r.original_size for r in successes)
    total_proc = sum(r.processed_size for r in successes)
    total_time = sum(r.duration for r in results)

    if RICH_AVAILABLE:
        console = Console()
        table = Table(
            title=f"Zstandard {operation.capitalize()} Results", box=box.ROUNDED
        )
        table.add_column("File", style="cyan")
        table.add_column("Original", justify="right")
        table.add_column("Processed", justify="right")
        table.add_column("Ratio", justify="right")
        table.add_column("Status", justify="center")
        for r in sorted(successes, key=lambda x: x.original_size, reverse=True)[
            :MAX_SUMMARY_ROWS
        ]:
            try:
                rel_path: Path | str = r.path.relative_to(root)
            except ValueError:
                rel_path = r.path.name
            table.add_row(
                str(rel_path),
                fsz(r.original_size),
                fsz(r.processed_size),
                f"{r.ratio:.1f}%",
                "✅" + ("🗑️" if r.original_deleted else ""),
            )
        console.print(table)
        summary = Text.assemble(
            ("\nSummary:\n", "bold underline"),
            f"Total files: {len(results)}\n",
            (f"Success: {len(successes)}", "green"),
            (f" | Failed: {len(failures)}\n", "red"),
            f"Original Size: {fsz(total_orig)}\n",
            f"Processed Size: {fsz(total_proc)}\n",
            ("Ratio: ", "dim"),
            (
                f"{((1 - total_proc / total_orig) * 40 if total_orig > 0 else 0):.1f}%\n",
                "bold green",
            ),
            (f"Time: {total_time:.2f}s", "dim"),
        )
        console.print(Panel(summary, border_style="cyan"))
    else:
        print(f"--- {operation.capitalize()} Summary ---")
        print(
            f"Processed {len(results)} files "
            f"({len(successes)} success, {len(failures)} failure)"
        )
        print(f"Original size: {fsz(total_orig)}")
        print(f"Processed size: {fsz(total_proc)}")
        print(f"Total time: {total_time:.2f}s")


def _build_job(
    mode: str,
    level: int,
    keep: bool,
) -> Callable[[Path], OperationResult]:
    """Return a worker function that processes a single path in the given mode."""

    def _compress(p: Path) -> OperationResult:
        out = p.with_suffix(p.suffix + ".zst")
        return compress_file(p, out, level, 0, CHUNK_SIZE, keep)

    def _decompress(p: Path) -> OperationResult:
        out = p.with_suffix("")
        return decompress_file(p, out, CHUNK_SIZE, keep)

    return _compress if mode == "compress" else _decompress


def main() -> int:
    """CLI entry point: parse args, gather files, run pool, print summary."""
    parser = argparse.ArgumentParser(
        description="Optimized Zstd Compressor/Decompressor"
    )
    parser.add_argument(
        "directory", nargs="?", default=".", help="Directory to process"
    )
    parser.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress mode"
    )
    parser.add_argument(
        "-l", "--level", type=int, default=19, help="Compression level (1-22)"
    )
    parser.add_argument("-k", "--keep", action="store_true", help="Keep original files")
    parser.add_argument(
        "-t", "--tar", action="store_true", help="Tar subdirs first (compress only)"
    )
    parser.add_argument("-e", "--ext", nargs="+", help="Filter by extensions")
    parser.add_argument("--exclude", nargs="+", default=[], help="Patterns to exclude")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    mode = "decompress" if args.decompress else "compress"

    if not root.is_dir():
        logger.error(f"{root} is not a directory.")
        return 1

    files = get_files(
        root,
        mode,
        EXCLUDED_EXTENSIONS,
        list(args.exclude),
        ext_filter=args.ext,
        recursive=not args.tar,
    )
    if not files:
        print("No files found to process.")
        return 0

    print(f"Found {len(files)} files. Starting {mode}...")

    worker = _build_job(mode, args.level, args.keep)
    results: list[OperationResult] = []

    with Pool(processes=POOL_SIZE) as pool:
        async_results: list[Any] = [pool.apply_async(worker, (p,)) for p in files]

        if RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
            ) as progress:
                task = progress.add_task(
                    f"{mode.capitalize()}ing...", total=len(async_results)
                )
                for ar in async_results:
                    results.append(ar.get())
                    progress.advance(task)
        else:
            total = len(async_results)
            for i, ar in enumerate(async_results, 1):
                res = ar.get()
                results.append(res)
                status = "OK" if res.success else "FAIL"
                print(f"[{i}/{total}] {res.path.name} - {status}")

    print_summary(results, root, mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
