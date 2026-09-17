#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import lzma
import os
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

CompressionResult = namedtuple(
    "CompressionResult",
    ["algorithm", "success", "compressed_size", "ratio", "time", "path", "error"],
)


def compress_brotli(data: bytes) -> bytes:
    return brotli.compress(data, quality=11)


def compress_zstd(data: bytes) -> bytes:
    cctx = zstd.ZstdCompressor(level=21)
    return cctx.compress(data)


def compress_lzma(data: bytes) -> bytes:
    return lzma.compress(data, preset=9)


def compress_bzip2(data: bytes) -> bytes:
    return bz2.compress(data, compresslevel=9)


def compress_gzip(data: bytes) -> bytes:
    buf = bytearray()
    with gzip.GzipFile(fileobj=__BytesIOProxy(buf), mode="wb", compresslevel=9) as f:
        f.write(data)
    return bytes(buf)


def compress_lz4(data: bytes) -> bytes:
    return lz4.frame.compress(data, compression_level=lz4.frame.COMPRESSIONLEVEL_MAX)


def compress_blosc(data: bytes) -> bytes:
    return blosc.compress(data, codec="zstd", clevel=9)


def compress_7z(data: bytes, base_name: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_file = Path(tmpdir) / f"{base_name}.tar"
        with open(temp_file, "wb") as f:
            f.write(data)
        archive_path = Path(tmpdir) / f"{base_name}.7z"
        with py7zr.SevenZipFile(archive_path, "w") as archive:
            archive.write(temp_file, arcname=temp_file.name)
        with open(archive_path, "rb") as f:
            return f.read()


class __BytesIOProxy:
    def __init__(self, buffer: bytearray):
        self.buffer = buffer

    def write(self, data: bytes) -> int:
        self.buffer.extend(data)
        return len(data)


def prepare_data(target_path: str) -> tuple[bytes, int, str]:
    path = Path(target_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {target_path}")
    if path.is_file():
        with open(path, "rb") as f:
            data = f.read()
        return (data, len(data), path.stem)
    elif path.is_dir():
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with tarfile.open(tmp_path, "w") as tar:
                tar.add(path, arcname=path.name)
            with open(tmp_path, "rb") as f:
                data = f.read()
            return (data, len(data), path.name)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    else:
        raise ValueError(f"Invalid path type: {target_path}")


def benchmark_compression(
    algorithm_name: str,
    compress_func,
    data: bytes,
    base_name: str,
    extension: str,
    original_size: int,
) -> CompressionResult:
    try:
        start_time = time.time()
        if algorithm_name == "7z":
            compressed = compress_func(data, base_name)
        else:
            compressed = compress_func(data)
        elapsed_time = time.time() - start_time
        compressed_size = len(compressed)
        ratio = compressed_size / original_size if original_size > 0 else 0
        path = Path(f"{base_name}{extension}")
        with open(path, "wb") as f:
            f.write(compressed)
        return CompressionResult(
            algorithm=algorithm_name,
            success=True,
            compressed_size=compressed_size,
            ratio=ratio,
            time=elapsed_time,
            path=str(path),
            error=None,
        )
    except Exception as e:
        return CompressionResult(
            algorithm=algorithm_name,
            success=False,
            compressed_size=0,
            ratio=0,
            time=0,
            path=None,
            error=str(e),
        )


def print_header(target: str, original_size: int):
    print(f"\n📦 Compressing: {target}\n")
    print(f"Original size: {original_size:,} bytes\n")
    print("COMPRESSION PROGRESS:")
    print("-" * 40)


def print_result(result: CompressionResult):
    if result.success:
        print(
            f"✓ {result.algorithm:<10} | Size: {result.compressed_size:>12,} | Ratio: {result.ratio:.4f} | Time: {result.time:.3f}s"
        )
    else:
        print(f"✗ {result.algorithm:<10} | Error: {result.error}")


def print_summary(results: list[CompressionResult], original_size: int):
    successful = [r for r in results if r.success]
    if not successful:
        print("\n✗ All compression attempts failed!")
        return None
    sorted_results = sorted(successful, key=lambda r: r.ratio)
    print("\n" + "=" * 40)
    print("TOP 3 COMPRESSION RESULTS")
    print("=" * 40)
    for idx, result in enumerate(sorted_results[:3], 1):
        bytes_saved = original_size - result.compressed_size
        print(
            f"{idx}\\. {result.algorithm:<10} | Size: {result.compressed_size:>12,} | Ratio: {result.ratio:.4f} | Saved: {bytes_saved:>12,} bytes"
        )
    print("=" * 40)
    return sorted_results[0]


def cleanup_files(results: list[CompressionResult], keep_result: CompressionResult):
    for result in results:
        if result.success and result.path and (result.path != keep_result.path):
            try:
                os.remove(result.path)
                print(f"✗ Deleted: {result.algorithm}")
            except OSError as e:
                print(f"⚠ Failed to delete {result.algorithm}: {e}")
    print(f"\n✓ Keeping best: {keep_result.algorithm} ({keep_result.path})")


def main():
    if len(sys.argv) != 2:
        print("Usage: python compression_benchmark.py <file_or_directory>")
        sys.exit(1)
    target_path = sys.argv[1]
    try:
        data, original_size, base_name = prepare_data(target_path)
    except Exception as e:
        print(f"✗ Error preparing data: {e}", file=sys.stderr)
        sys.exit(1)
    print_header(target_path, original_size)
    algorithms = [
        ("brotli", compress_brotli, ".br"),
        ("zstd", compress_zstd, ".zst"),
        ("xz", compress_lzma, ".xz"),
        ("bz2", compress_bzip2, ".bz2"),
        ("gzip", compress_gzip, ".gz"),
        ("lz4", compress_lz4, ".lz4"),
        ("blosc", compress_blosc, ".blosc"),
        ("7z", compress_7z, ".7z"),
    ]
    results = []
    for algo_name, compress_func, extension in algorithms:
        result = benchmark_compression(
            algo_name, compress_func, data, base_name, extension, original_size
        )
        results.append(result)
        print_result(result)
    best_result = print_summary(results, original_size)
    if best_result:
        cleanup_files(results, best_result)
        print("\n✓ Done!")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
