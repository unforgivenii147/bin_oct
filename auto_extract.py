#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import lzma
import multiprocessing as mp
import pathlib
import tarfile
import zipfile

import brotli
import lz4.frame
import py7zr
import zstandard as zstd

SUPPORTED_EXTENSIONS = {
    "gz": gzip.open,
    "xz": lzma.open,
    "bz2": bz2.open,
    "7z": py7zr.SevenZipFile,
    "lz4": lz4.frame.open,
    "br": brotli.decompress,
    "zst": zstd.ZstdDecompressor,
    "zip": zipfile.ZipFile,
    "whl": zipfile.ZipFile,
}
TAR_EXTENSIONS = [
    "tar.gz",
    "tar.xz",
    "tar.bz2",
    "tar.7z",
    "tar.zst",
    "tar.br",
    "tar.lz4",
    "tar",
]


def extract_file(path):
    print(f"Extracting: {path}")
    try:
        if path.suffix in SUPPORTED_EXTENSIONS:
            if path.suffix == ".gz":
                with (
                    gzip.open(path, "rb") as f_in,
                    open(path.with_suffix(""), "wb") as f_out,
                ):
                    f_out.write(f_in.read())
            elif path.suffix == ".xz":
                with (
                    lzma.open(path, "rb") as f_in,
                    open(path.with_suffix(""), "wb") as f_out,
                ):
                    f_out.write(f_in.read())
            elif path.suffix == ".bz2":
                with (
                    bz2.open(path, "rb") as f_in,
                    open(path.with_suffix(""), "wb") as f_out,
                ):
                    f_out.write(f_in.read())
            elif path.suffix == ".7z":
                with py7zr.SevenZipFile(path, mode="r") as archive:
                    archive.extractall(path=path.parent)
            elif path.suffix == ".lz4":
                with (
                    lz4.frame.open(path, mode="rb") as f_in,
                    open(path.with_suffix(""), "wb") as f_out,
                ):
                    f_out.write(f_in.read())
            elif path.suffix == ".br":
                with open(path, "rb") as f_in:
                    data = f_in.read()
                    decompressed_data = brotli.decompress(data)
                    with open(path.with_suffix(""), "wb") as f_out:
                        f_out.write(decompressed_data)
            elif path.suffix == ".zst":
                with open(path, "rb") as f_in:
                    dctx = zstd.ZstdDecompressor()
                    with open(path.with_suffix(""), "wb") as f_out:
                        dctx.copy_stream(f_in, f_out)
            elif path.suffix == ".zip" or path.suffix == ".whl":
                with zipfile.ZipFile(path, "r") as zip_ref:
                    zip_ref.extractall(path.parent)
        elif path.suffix in TAR_EXTENSIONS:
            with tarfile.open(path, "r:*") as tar_ref:
                tar_ref.extractall(path=path.parent)
    except Exception as e:
        print(f"Failed to extract {path}: {e}")


def main():
    current_dir = pathlib.Path(".")
    archive_files = list(current_dir.rglob("*.*"))
    archive_files = [
        f
        for f in archive_files
        if f.suffix[1:] in SUPPORTED_EXTENSIONS or f.suffix in TAR_EXTENSIONS
    ]
    with mp.Pool(processes=mp.cpu_count()) as pool:
        pool.map(extract_file, archive_files)


if __name__ == "__main__":
    raise SystemExit(main())
