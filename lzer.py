#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path

import lz4.frame

CHUNK_SIZE = 1024 * 1024
CHUNK_THRESHOLD = 5 * 1024 * 1024
COMPRESSED_EXT = ".lz4"
EXT = {".gz", ".br", ".xz", ".zst", ".bz2", ".zip", ".whl", ".lz4"}


def compress_file(
    src_path: Path, compression_level=lz4.frame.COMPRESSIONLEVEL_MAX
) -> None:
    if src_path.is_dir():
        return
    if src_path.suffix == COMPRESSED_EXT:
        return
    dst_path = src_path.with_name(src_path.name + COMPRESSED_EXT)
    try:
        file_size = src_path.stat().st_size
        with open(src_path, "rb") as f_in, open(dst_path, "wb") as f_out:
            compressor = lz4.frame.LZ4FrameCompressor(
                compression_level=compression_level
            )
            if file_size > CHUNK_THRESHOLD:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f_out.write(compressor.compress_chunk(chunk))
            else:
                data = f_in.read()
                f_out.write(compressor.begin())
                f_out.write(compressor.compress(data))
            f_out.write(compressor.flush())
        os.remove(src_path)
    except Exception as e:
        print(f"Failed to compress {src_path}: {e}")
        try:
            if dst_path.exists():
                dst_path.unlink()
        except Exception:
            pass


def compress_files_recursive(directory: str = ".") -> None:
    for root, _, files in os.walk(directory):
        for filename in files:
            path = Path(root) / filename
            if path.suffix in EXT or ".tar." in path.name:
                continue
            compress_file(path)


if __name__ == "__main__":
    compress_files_recursive(".")
