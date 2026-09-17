#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import lzma
import sys
import tarfile
import tempfile
import time
from collections import namedtuple
from pathlib import Path

import blosc
import brotli
import lz4.frame
import py7zr
import zstandard as zstd

ALGORITHMS = [
    ("brotli", ".br", compress_brotli),
    ("zstd", ".zst", compress_zstd),
    ("xz", ".xz", compress_xz),
    ("bz2", ".bz2", compress_bz2),
    ("gzip", ".gz", compress_gzip),
    ("lz4", ".lz4", compress_lz4),
    ("blosc", ".blosc", compress_blosc),
]
CompressionResult = namedtuple(
    "CompressionResult", ["name", "ext", "size", "ratio", "elapsed", "output_path"]
)


def compress_brotli(data: bytes) -> bytes:
    return brotli.compress(data, quality=11)


def compress_zstd(data: bytes) -> bytes:
    cctx = zstd.ZstdCompressor(level=21)
    return cctx.compress(data)


def compress_xz(data: bytes) -> bytes:
    return lzma.compress(data, preset=9)


def compress_bz2(data: bytes) -> bytes:
    return bz2.compress(data, compresslevel=9)


def compress_gzip(data: bytes) -> bytes:
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as f:
        f.write(data)
    return buf.getvalue()


def compress_lz4(data: bytes) -> bytes:
    return lz4.frame.compress(data, compression_level=lz4.frame.COMPRESSIONLEVEL_MAX)


def compress_blosc(data: bytes) -> bytes:
    blosc.set_compressor("zstd")
    return blosc.compress(data, clevel=9, shuffle=blosc.BITSHUFFLE)


def compress_7z(data: bytes, output_path: Path) -> bytes:
    tmp_input = Path(tempfile.mkstemp(suffix=".tmp"))
    try:
        tmp_input.write_bytes(data)
        with py7zr.SevenZipFile(output_path, mode="w") as archive:
            archive.write(tmp_input, tmp_input.name)
        return output_path.read_bytes()
    finally:
        if tmp_input.exists():
            tmp_input.unlink()


def prepare_input(target: Path) -> tuple[bytes, str]:
    if target.is_file():
        return target.read_bytes(), target.name
    elif target.is_dir():
        tmp_tar = Path(tempfile.mktemp(suffix=".tar"))
        try:
            with tarfile.open(tmp_tar, "w") as tar:
                tar.add(target, arcname=target.name)
            data = tmp_tar.read_bytes()
        finally:
            if tmp_tar.exists():
                tmp_tar.unlink()
        return data, target.name
    else:
        raise ValueError(f"Path is neither a file nor a directory: {target}")


def run_benchmark(target: Path) -> None:
    print(f"\n📦 Compressing: {target}\n")
    data, base_name = prepare_input(target)
    original_size = len(data)
    print(f"Original size: {original_size:,} bytes\n")
    print("COMPRESSION PROGRESS:")
    print("-" * 40)
    results = []
    for name, ext, fn in ALGORITHMS:
        output_path = Path(f"{base_name}{ext}")
        try:
            t0 = time.perf_counter()
            compressed = fn(data)
            elapsed = time.perf_counter() - t0
            output_path.write_bytes(compressed)
            size = len(compressed)
            ratio = size / original_size
            print(
                f"✓ {name:<10} | Size: {size:>12,} | Ratio: {ratio:.4f} | Time: {elapsed:.3f}s"
            )
            results.append(
                CompressionResult(name, ext, size, ratio, elapsed, output_path)
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0 if "t0" in dir() else 0.0
            print(f"✗ {name:<10} | ERROR: {e}")
            if output_path.exists():
                output_path.unlink()
    output_path_7z = Path(f"{base_name}.7z")
    try:
        t0 = time.perf_counter()
        compress_7z(data, output_path_7z)
        elapsed = time.perf_counter() - t0
        size = output_path_7z.stat().st_size
        ratio = size / original_size
        print(
            f"✓ {'7z':<10} | Size: {size:>12,} | Ratio: {ratio:.4f} | Time: {elapsed:.3f}s"
        )
        results.append(
            CompressionResult("7z", ".7z", size, ratio, elapsed, output_path_7z)
        )
    except Exception as e:
        print(f"✗ {'7z':<10} | ERROR: {e}")
        if output_path_7z.exists():
            output_path_7z.unlink()
    if not results:
        print("\n⚠ All compression algorithms failed. No output files created.")
        return
    results.sort(key=lambda r: r.ratio)
    top3 = results[:3]
    best = results[0]
    print("\n" + "=" * 40)
    print("TOP 3 COMPRESSION RESULTS")
    print("-" * 40)
    for rank, r in enumerate(top3, 1):
        saved = original_size - r.size
        print(
            f"{rank}. {r.name:<10} | Size: {r.size:>12,} | Ratio: {r.ratio:.4f} | Saved: {saved:>12,} bytes"
        )
    print(f"\n✓ Keeping best: {best.name} ({best.output_path.name})")
    for r in results[1:]:
        try:
            if r.output_path.exists():
                r.output_path.unlink()
            print(f"✗ Deleted: {r.name}")
        except OSError as e:
            print(f"⚠ Could not delete {r.name}: {e}")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <file_or_directory>")
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.exists():
        print(f"⚠ Error: '{target}' does not exist.")
        sys.exit(1)
    run_benchmark(target)


if __name__ == "__main__":
    raise SystemExit(main())
