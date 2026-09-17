#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import brotli

BROTLI_QUALITY = 11
CHUNK_SIZE = 1024 * 64


def compress_stream(input_stream, output_path: Path):
    compressor = brotli.Compressor(quality=BROTLI_QUALITY)
    try:
        with open(output_path, "wb") as f_out:
            while True:
                chunk = input_stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(compressor.process(chunk))
            f_out.write(compressor.finish())
        print(f"✅ Compressed: {output_path.name}")
    except Exception as e:
        print(f"❌ Error compressing {output_path.name}: {e}")


def process_directory(dir_path: Path):
    output_br = dir_path.with_name(f"{dir_path.name}.tar.br")
    tar_buffer = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        compress_stream(tar_buffer, output_br)
    except Exception as e:
        print(f"❌ Failed to archive directory {dir_path.name}: {e}")


def process_file(path: Path):
    output_br = path.with_name(f"{path.name}.br")
    try:
        with open(path, "rb") as f_in:
            compress_stream(f_in, output_br)
    except Exception as e:
        print(f"❌ Failed to open file {path.name}: {e}")


def main():
    current_dir = Path(".")
    subdirs = [
        d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    files = [
        f
        for f in current_dir.iterdir()
        if f.is_file() and f.suffix != ".br" and f.name != Path(__file__).name
    ]
    if not subdirs and not files:
        print("No files or subdirectories found to compress.")
        return
    print(f"🚀 Found {len(subdirs)} subdirs to TAR+BR, and {len(files)} files to BR.")
    print(f"⚡ Starting parallel processing pool (Quality Level: {BROTLI_QUALITY})...")
    with ThreadPoolExecutor() as executor:
        for directory in subdirs:
            executor.submit(process_directory, directory)
        for file in files:
            executor.submit(process_file, file)
    print("🎉 All operations completed successfully!")


if __name__ == "__main__":
    raise SystemExit(main())
