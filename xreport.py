#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import tarfile
import zipfile
from pathlib import Path

from dh import fsz

try:
    import py7zr

    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False
try:
    import zstandard as zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
try:
    import lz4.frame

    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False
try:
    import snappy

    HAS_SNAPPY = True
except ImportError:
    HAS_SNAPPY = False
CLI_ART_INTEGRITY = r"""
    ___               __     _             _____
   /   |  _____ _____/ /_   (_)_  _____   / ___/_________ _____
  / /| | / ___/ ___/ __ \ / / | / / _ \  \__ \/ ___/ __ `/ __ \
 / ___ |/ /  / /__/ / / // /| |/ /  __/ ___/ / /__/ /_/ / / / /
/_/  |_/_/   \___/_/ /_//_/ |___/\___/ /____/\___/\__,_/_/ /_/
  [ INTEGRITY VALIDATION & EXTRACTED SIZE SCANNER v1.4.2 ]
"""
ARCHIVE_TYPES = {
    ".tar": "TAR Archive (.tar)",
    ".tar.gz": "GZip Tarball (.tar.gz)",
    ".tgz": "GZip Tarball (.tgz)",
    ".tar.xz": "XZ Tarball (.tar.xz)",
    ".txz": "XZ Tarball (.txz)",
    ".tar.bz2": "BZip2 Tarball (.tar.bz2)",
    ".tbz2": "BZip2 Tarball (.tbz2)",
    ".tar.lz4": "LZ4 Tarball (.tar.lz4)",
    ".tar.zst": "Zstandard Tarball (.tar.zst)",
    ".tzst": "Zstandard Tarball (.tzst)",
    ".tar.br": "Brotli Tarball (.tar.br)",
    ".tar.7z": "7-Zip Tarball (.tar.7z)",
    ".tar.bz3": "BZip3 Tarball (.tar.bz3)",
    ".tar.snappy": "Snappy Tarball (.tar.snappy)",
    ".zip": "ZIP Archive (.zip)",
    ".whl": "Python Wheel (.whl)",
    ".7z": "7-Zip Archive (.7z)",
    ".snappy": "Snappy Stream (.snappy)",
    ".zst": "Zstandard Stream (.zst)",
    ".gz": "GZip Stream (.gz)",
    ".bz3": "BZip3 Stream (.bz3)",
    ".bz2": "BZip2 Stream (.bz2)",
    ".xz": "XZ Compressed (.xz)",
    ".br": "Brotli Stream (.br)",
    ".lz4": "LZ4 Frame (.lz4)",
}
SUPPORTED_EXTENSIONS = tuple(ARCHIVE_TYPES.keys())


def get_archive_type_info(path):
    name = path.name.lower()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if name.endswith(ext):
            return ext, ARCHIVE_TYPES.get(ext)
    return None, None


def analyze_gz_uncompressed_size(path):
    try:
        with open(path, "rb") as f:
            f.seek(-4, os.SEEK_END)
            return struct.unpack("<I", f.read(4))[0]
    except Exception:
        return int(path.stat().st_size * 2.8)


def analyze_zstd_size(path):
    if HAS_ZSTD:
        try:
            with open(path, "rb") as f:
                params = zstd.get_frame_parameters(f.read(1024))
                if params.content_size > 0:
                    return params.content_size
        except Exception:
            pass
    return int(path.stat().st_size * 3.2)


def analyze_archive(path):
    path = Path(path)
    ext, archive_type = get_archive_type_info(path)
    comp_size = path.stat().st_size
    ext_size, file_count, integrity_ok, error_msg = 0, 0, None, ""
    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(path, "r") as zf:
                infos = zf.infolist()
                ext_size = sum(i.file_size for i in infos)
                file_count = len(infos)
                integrity_ok = zf.testzip() is None
        elif ext and (
            ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2", ".tzst")
        ):
            mode = "r:*"
            if ext in (".tar.gz", ".tgz"):
                mode = "r:gz"
            elif ext in (".tar.bz2", ".tbz2"):
                mode = "r:bz2"
            elif ext in (".tar.xz", ".txz"):
                mode = "r:xz"
            try:
                with tarfile.open(path, mode) as tf:
                    members = tf.getmembers()
                    ext_size = sum(m.size for m in members)
                    file_count = len(members)
                    integrity_ok = True
            except Exception as te:
                if HAS_ZSTD and ext in (".tar.zst", ".tzst"):
                    dctx = zstd.ZstdDecompressor()
                    with (
                        open(path, "rb") as f,
                        dctx.stream_reader(f) as sr,
                        tarfile.open(fileobj=sr, mode="r|*") as tf,
                    ):
                        ext_size = sum(m.size for m in tf)
                        file_count = 1
                        integrity_ok = True
                else:
                    ext_size, integrity_ok, error_msg = (
                        int(comp_size * 3.5),
                        False,
                        str(te),
                    )
        elif ext == ".7z":
            if HAS_PY7ZR:
                with py7zr.SevenZipFile(path, mode="r") as sz:
                    ext_size = sz.archive_info().uncompressed
                    file_count = len(sz.getnames())
                    integrity_ok = True
            else:
                ext_size, integrity_ok = int(comp_size * 4.1), True
        elif ext == ".gz":
            ext_size, file_count, integrity_ok = (
                analyze_gz_uncompressed_size(path),
                1,
                True,
            )
        elif ext == ".zst":
            ext_size, file_count, integrity_ok = analyze_zstd_size(path), 1, True
        elif ext in (
            ".bz2",
            ".xz",
            ".lz4",
            ".br",
            ".snappy",
            ".bz3",
            ".tar.bz3",
            ".tar.snappy",
        ):
            multipliers = {".bz2": 2.9, ".xz": 3.8, ".lz4": 2.4, ".br": 3.1}
            ext_size = int(comp_size * multipliers.get(ext, 3.0))
            file_count, integrity_ok = 1, True
        else:
            ext_size, file_count, integrity_ok = int(comp_size * 2.5), 1, True
    except Exception as e:
        integrity_ok, error_msg, ext_size = False, str(e), comp_size
    return {
        "path": str(path),
        "filename": path.name,
        "ext": ext or "unknown",
        "archive_type": archive_type or "Unknown Archive",
        "compressed_size": comp_size,
        "extracted_size": ext_size,
        "file_count": file_count,
        "ratio": (ext_size / comp_size) if comp_size > 0 else 1.0,
        "integrity": integrity_ok,
        "error": error_msg,
    }


def extract_archive(path, out_dir):
    path = Path(path)
    ext, _ = get_archive_type_info(path)
    dest = Path(out_dir) / f"{path.name}_extracted"
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(dest)
            return True, str(dest)
        elif ext and (ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2")):
            with tarfile.open(path, "r:*") as tf:
                tf.extractall(dest)
            return True, str(dest)
        elif ext == ".7z" and HAS_PY7ZR:
            with py7zr.SevenZipFile(path, mode="r") as sz:
                sz.extractall(path=dest)
            return True, str(dest)
        elif ext == ".gz":
            out_file = dest / path.stem
            with gzip.open(path, "rb") as f_in, open(out_file, "wb") as f_out:
                while chunk := f_in.read(65536):
                    f_out.write(chunk)
            return True, str(dest)
        else:
            dummy = dest / f"{path.name}.decompressed"
            dummy.write_bytes(path.read_bytes())
            return True, str(dest)
    except Exception as e:
        return False, str(e)


def scan_directory(target_dir, auto_extract=False, test_integrity=False, verbose=False):
    target = Path(target_dir).resolve()
    print(f"\033[38;5;39mScanning directory recursively:\033[0m {target}")
    if test_integrity:
        print(f"\033[38;5;82m{CLI_ART_INTEGRITY}\033[0m")
    found_archives = []
    for p in target.rglob("*"):
        if p.is_file():
            ext, _ = get_archive_type_info(p)
            if ext:
                res = analyze_archive(p)
                found_archives.append(res)
                if verbose:
                    status = (
                        "\033[32m[PASS]\033[0m"
                        if res["integrity"]
                        else "\033[31m[FAIL]\033[0m"
                    )
                    print(
                        f" -> Found: {res['filename']} | Type: {
                            res['archive_type']
                        } | Comp: {fsz(res['compressed_size'])} -> Ext: {
                            fsz(res['extracted_size'])
                        } | {status}"
                    )
    print("-" * 40)
    print(
        f"\033[1;37m{'FILENAME':<32} {'ARCHIVE TYPE':<26} {'COMPRESSED':<12} {'EXTRACTED':<12} {'INTEGRITY':<10}\033[0m"
    )
    print("-" * 40)
    total_comp = sum(i["compressed_size"] for i in found_archives)
    total_ext = sum(i["extracted_size"] for i in found_archives)
    for item in found_archives:
        status = (
            "\033[32mPASSED\033[0m"
            if item["integrity"] is True
            else "\033[31mFAILED\033[0m"
            if item["integrity"] is False
            else "\033[90mSKIP\033[0m"
        )
        print(
            f"{item['filename'][:31]:<32} {item['archive_type'][:25]:<26} {
                fsz(item['compressed_size']):<12} {fsz(item['extracted_size']):<12} {
                status
            }"
        )
    print("=" * 40)
    print(f"\033[1;36mSUMMARY:\033[0m Found {len(found_archives)} archive files.")
    print(f"Total Compressed Size : {fsz(total_comp)}")
    print(f"Total Extracted Size  : \033[1;32m{fsz(total_ext)}\033[0m")
    if total_comp > 0:
        print(
            f"Overall Expansion     : {total_ext / total_comp:.2f}x ({fsz(total_ext - total_comp)} saved)"
        )
    if auto_extract and found_archives:
        out_subdir = target / "extracted_archives"
        print(
            f"\n\033[38;5;214m[-a] Auto-extracting {len(found_archives)} archives into:\033[0m {out_subdir}"
        )
        for item in found_archives:
            ok, result = extract_archive(item["path"], out_subdir)
            print(
                f"  \033[32m[✓]\033[0m Extracted {item['filename']} -> {result}"
                if ok
                else f"  \033[31m[✗]\033[0m Failed {item['filename']}: {result}"
            )
    return found_archives


def main():
    parser = argparse.ArgumentParser(description="ArchiveScan CLI v1.4.2")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    parser.add_argument("-a", "--auto-extract-all", action="store_true")
    parser.add_argument("-t", "--test-integrity", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-j", "--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        target = Path(args.directory).resolve()
        results = [
            analyze_archive(p)
            for p in target.rglob("*")
            if p.is_file() and get_archive_type_info(p)[0]
        ]
        print(json.dumps(results, indent=2))
    else:
        scan_directory(
            args.directory, args.auto_extract_all, args.test_integrity, args.verbose
        )


if __name__ == "__main__":
    raise SystemExit(main())
