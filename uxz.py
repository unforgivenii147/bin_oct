#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import tarfile
from pathlib import Path

from dh import get_files
from lzma_mt import LZMADecompressor

MEM_LIMIT = 104857600


def decompress_file(path: Path) -> bool:
    fname = path.name
    if fname.endswith(".tar.xz"):
        extract_path = path.parent / f"{fname.replace('.tar.xz', '')}"
        with tarfile.open(path, "r:xz") as tar:
            tar.extractall(path=extract_path, filter="data")
        return True
    elif fname.endswith(".xz"):
        compressed_data = path.read_bytes()
        out_path = path.parent / f"{fname.replace('.xz', '')}"
        decompressor = LZMADecompressor(memlimit=MEM_LIMIT, threads=4)
        decompressed_data = decompressor.decompress(compressed_data)
        with out_path.open("wb") as f:
            f.write(decompressed_data)
        return True
    return False


def main() -> None:
    sys.argv[1:]
    successful = 0
    errors = 0
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".xz", ".tar.xz"])
    if not files:
        print("No files to decompress")
        return
    for i, path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] Processing...")
        real_path = path
        if "/storage/emulated/0" in str(path):
            path_str = str(path).replace("/storage/emulated/0", "/sdcard")
            real_path = Path(path_str)
        if decompress_file(real_path):
            successful += 1
            real_path.unlink()
        else:
            errors += 1
    print(f"successfull: {successful}\nerrors: {errors}")


if __name__ == "__main__":
    raise SystemExit(main())
