#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import lzma
import pickle
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path

try:
    import brotli
except ImportError:
    brotli = None
try:
    import zstandard

    zstd_available = True
except ImportError:
    zstd_available = False
try:
    import py7zr
except ImportError:
    py7zr = None


def try_decompress(filename: str) -> None:
    print(f"Attempting to decompress: {filename}\n")
    compression_methods = {
        "zlib": zlib.decompress,
        "bz2": bz2.decompress,
        "gzip": gzip.decompress,
        "lzma": lzma.decompress,
        "pickle": pickle.loads,
    }
    if brotli:
        compression_methods["brotli"] = brotli.decompress
    if zstd_available:

        def zstd_decompress_all(data) -> bytes:
            try:
                dctx = zstandard.ZstdDecompressor()
                return dctx.decompress(data)
            except zstandard.ZstdError as e:
                raise ValueError(msg) from e

        compression_methods["zstandard"] = zstd_decompress_all
    if py7zr:
        pass
    try:
        file_data = Path(filename).read_bytes()
    except FileNotFoundError:
        print(f"Error: File not found at {filename}\n")
        return
    except Exception as e:
        print(f"Error reading file {filename}: {e}\n")
        return
    success = False
    for name, func in compression_methods.items():
        try:
            print(f"Trying {name}...")
            decompressed_data = func(file_data)
            if decompressed_data and len(decompressed_data) < len(file_data) * 10:
                print(f"""  SUCCESS: Decompressed using {name}. Size: {len(decompressed_data)} bytes.
""")
                success = True
            else:
                print(f"""  FAILED: {name} did not yield valid decompressed data (size: {len(decompressed_data)}).
""")
        except Exception as e:
            print(f"  FAILED: {name} raised an exception: {type(e).__name__}: {e}\n")
    if tarfile.is_tarfile(filename):
        try:
            print("Trying tarfile...")
            with tarfile.open(filename, "r") as tar:
                members = tar.getmembers()
                if members:
                    print(
                        f"""  SUCCESS: Opened as tar archive with {len(members)} members. First member: {members[0].name}
"""
                    )
                    success = True
                else:
                    print("  FAILED: tarfile is empty.\n")
        except Exception as e:
            print(f"  FAILED: tarfile opened with exception: {type(e).__name__}: {e}\n")
    if zipfile.is_zipfile(filename):
        try:
            print("Trying zipfile...")
            with zipfile.ZipFile(filename, "r") as zip_ref:
                file_list = zip_ref.namelist()
                if file_list:
                    print(f"""  SUCCESS: Opened as zip archive with {len(file_list)} files. First file: {file_list[0]}
""")
                    success = True
                else:
                    print("  FAILED: zipfile is empty.\n")
        except Exception as e:
            print(f"  FAILED: zipfile opened with exception: {type(e).__name__}: {e}\n")
    if py7zr:
        try:
            print("Trying py7zr (7z archive)...")
            with py7zr.SevenZipFile(filename, mode="r") as z:
                file_list = z.getnames()
                if file_list:
                    print(f"""  SUCCESS: Opened as 7z archive with {len(file_list)} files. First file: {file_list[0]}
""")
                    success = True
                else:
                    print("  FAILED: py7zr archive is empty.\n")
        except Exception as e:
            print(f"  FAILED: py7zr opened with exception: {type(e).__name__}: {e}\n")
    if not success:
        print(
            "No compression or archive format was successfully identified and decompressed.\n"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python your_script_name.py <filename>\n")
        sys.exit(1)
    input_filename = sys.argv[1]
    try_decompress(input_filename)
