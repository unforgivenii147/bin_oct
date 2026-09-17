#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a parallel file/directory compressor & decompressor CLI using pylzma.

The script:
- Accepts paths to files/directories (or defaults to current directory recursively).
- Compresses: files -> .7z, directories -> .tar.7z (tar then LZMA), or decompresses
  .7z/.tar.7z back to originals.
- Runs jobs in parallel with multiprocessing.Pool.apply_async using a fixed pool of 8 workers.
- Provides flags: -d/--decompress, -k/--keep.
- Uses loguru for logging, pathlib for all path handling, and full type annotations.
- Prints a final summary of sizes and space freed/used.
"""

from __future__ import annotations

import argparse
import io
import shutil
import tarfile
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import pylzma
from loguru import logger

_COMPRESS_OPTS: dict[str, int] = {
    "dictionary": 27,
    "fastBytes": 273,
    "algorithm": 2,
}

_POOL_SIZE: int = 8


def fsz(size: float) -> str:
    """Format a byte size into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def gsz(path: Path) -> int:
    """Compute the total size in bytes of a file or directory tree."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total: int = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def _format_result(
    action: str,
    src: Path,
    dst: Path,
    original_size: int,
    compressed_size: int,
    extra_line: str | None = None,
) -> str:
    """Build a consistent summary string for compress/decompress results."""
    if original_size > 0:
        ratio = (1 - compressed_size / original_size) * 40
    else:
        ratio = 0.0
    space_freed = original_size - compressed_size
    lines = [
        f"{action} {src} -> {dst}",
        f"  Original: {fsz(original_size)} -> Compressed: {fsz(compressed_size)}",
        f"  Ratio: {ratio:.1f}% | Space freed: {fsz(max(0, space_freed))}",
    ]
    if extra_line:
        lines.append(extra_line)
    return "\n".join(lines)


def _compress(src: Path, keep: bool) -> str:
    """Compress a file to .7z or a directory to .tar.7z using pylzma."""
    src = Path(src)
    try:
        original_size = gsz(src)
        if src.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                tar.add(src, arcname=src.name)
            compressed = pylzma.compress(buf.getvalue(), **_COMPRESS_OPTS)
            dst = src.parent / f"{src.name}.tar.7z"
            dst.write_bytes(compressed)
            compressed_size = dst.stat().st_size
            if not keep:
                shutil.rmtree(src)
            return _format_result(
                "Compressed", src, dst, original_size, compressed_size
            )
        if src.is_file():
            data = src.read_bytes()
            compressed = pylzma.compress(data, **_COMPRESS_OPTS)
            dst = src.parent / f"{src.name}.7z"
            dst.write_bytes(compressed)
            compressed_size = dst.stat().st_size
            if not keep:
                src.unlink()
            return _format_result(
                "Compressed", src, dst, original_size, compressed_size
            )
        return f"Skipped {src} (not a file or directory)"
    except Exception as e:
        return f"Error compressing {src}: {e}"


def _decompress(src: Path, keep: bool) -> str:
    """Decompress a .7z file or .tar.7z archive using pylzma."""
    src = Path(src)
    try:
        if not src.is_file():
            return f"Skipped {src} (not a file)"
        compressed_size = src.stat().st_size
        data = src.read_bytes()
        decompressed = pylzma.decompress(data)
        if src.name.endswith(".tar.7z"):
            dst = src.parent / src.name[: -len(".tar.7z")]
            dst.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO(decompressed)
            with tarfile.open(fileobj=buf, mode="r") as tar:
                tar.extractall(path=dst)
            if not keep:
                src.unlink()
            decompressed_size = gsz(dst)
            extra = f"  Space used: {fsz(decompressed_size - compressed_size)}"
            return _format_result(
                "Decompressed",
                src,
                dst,
                compressed_size,
                decompressed_size,
                extra_line=extra,
            )
        if src.name.endswith(".7z"):
            dst = src.parent / src.name[: -len(".7z")]
            dst.write_bytes(decompressed)
            if not keep:
                src.unlink()
            decompressed_size = dst.stat().st_size
            extra = f"  Space used: {fsz(decompressed_size - compressed_size)}"
            return _format_result(
                "Decompressed",
                src,
                dst,
                compressed_size,
                decompressed_size,
                extra_line=extra,
            )
        return f"Skipped {src} (not a .7z file)"
    except Exception as e:
        return f"Error decompressing {src}: {e}"


def _collect_targets(paths: Sequence[str], mode: str) -> list[Path]:
    """Collect unique target paths to process based on mode."""
    targets: list[Path] = []
    cwd = Path.cwd()
    if mode == "compress":
        if not paths:
            for p in Path(".").rglob("*"):
                if p.is_file() and not p.name.endswith(".7z"):
                    targets.append(p.resolve())
        else:
            for s in paths:
                p = Path(s)
                if not p.exists():
                    logger.warning(f"{p} does not exist, skipping")
                    continue
                p_resolved = p.resolve()
                if p_resolved == cwd and p.is_dir():
                    logger.warning(
                        "Processing contents of '.' recursively instead of compressing it as a single archive"
                    )
                    for child in p.rglob("*"):
                        if child.is_file() and not child.name.endswith(".7z"):
                            targets.append(child.resolve())
                else:
                    targets.append(p_resolved)
    else:
        if not paths:
            for p in Path(".").rglob("*"):
                if p.is_file() and p.name.endswith(".7z"):
                    targets.append(p.resolve())
        else:
            for s in paths:
                p = Path(s)
                if not p.exists():
                    logger.warning(f"{p} does not exist, skipping")
                    continue
                if p.is_file() and p.name.endswith(".7z"):
                    targets.append(p.resolve())
                elif p.is_dir():
                    for child in p.rglob("*"):
                        if child.is_file() and child.name.endswith(".7z"):
                            targets.append(child.resolve())
    seen: set[Path] = set()
    out: list[Path] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _compress_star(args: tuple[Path, bool]) -> str:
    """Wrapper for Pool.apply_async using star-args for _compress."""
    return _compress(*args)


def _decompress_star(args: tuple[Path, bool]) -> str:
    """Wrapper for Pool.apply_async using star-args for _decompress."""
    return _decompress(*args)


def _build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Compress/decompress files and directories using pylzma "
            "with parallel processing (fixed pool of 8 workers)"
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory recursively)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress mode (default: compress)",
    )
    parser.add_argument(
        "-k",
        "--keep",
        action="store_true",
        help="Keep original files after processing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: parse args, dispatch jobs, and print summary."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    mode = "decompress" if args.decompress else "compress"
    targets = _collect_targets(args.paths, mode)
    if not targets:
        print(f"No items found to {mode}")
        return 0
    print(f"{mode.capitalize()}ing {len(targets)} item(s)...")

    total_original = sum(gsz(t) for t in targets)

    worker_func = _decompress_star if mode == "decompress" else _compress_star
    payloads: Iterable[tuple[Path, bool]] = ((t, bool(args.keep)) for t in targets)

    with Pool(processes=_POOL_SIZE) as pool:
        async_results: list[Any] = [
            pool.apply_async(worker_func, (payload,)) for payload in payloads
        ]
        results: list[str] = [r.get() for r in async_results]

    for res in results:
        print(res)

    if mode == "compress":
        total_compressed = 0
        for t in targets:
            if t.is_dir():
                dst = t.parent / f"{t.name}.tar.7z"
            else:
                dst = t.parent / f"{t.name}.7z"
            if dst.exists():
                total_compressed += dst.stat().st_size
        if total_original > 0:
            total_ratio = (1 - total_compressed / total_original) * 40
            total_freed = total_original - total_compressed
            print("=" * 40)
            print("SUMMARY:")
            print(f"  Total original size: {fsz(total_original)}")
            print(f"  Total compressed size: {fsz(total_compressed)}")
            print(f"  Overall compression ratio: {total_ratio:.1f}%")
            print(f"  Total space freed: {fsz(max(0, total_freed))}")
    else:
        total_decompressed = 0
        for t in targets:
            if t.name.endswith(".tar.7z"):
                dst = t.parent / t.name[: -len(".tar.7z")]
            else:
                dst = t.parent / t.name[: -len(".7z")]
            total_decompressed += gsz(dst)
        total_space_used = total_decompressed - total_original
        print("=" * 40)
        print("SUMMARY:")
        print(f"  Total compressed size: {fsz(total_original)}")
        print(f"  Total decompressed size: {fsz(total_decompressed)}")
        print(f"  Total space used: {fsz(total_space_used)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
