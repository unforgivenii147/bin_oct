#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import tarfile
import tempfile
import zipfile
from multiprocessing import Pool, cpu_count
from pathlib import Path

try:
    import py7zr
except ImportError:
    py7zr = None
try:
    import brotli
except ImportError:
    brotli = None
try:
    import zstandard
except ImportError:
    zstandard = None


def collect_items(root_dirs, skip_patterns=None):
    if skip_patterns is None:
        skip_patterns = {".git"}
    items = []
    for root_dir in root_dirs:
        root_path = Path(root_dir)
        for path in root_path.rglob("*"):
            if any(part in skip_patterns for part in path.parts):
                continue
            if path.is_file():
                items.append(path)
    return items


def search_in_archive(archive_path, pattern):
    results = []
    pattern_lower = pattern.lower()
    archive_rel = archive_path.relative_to(Path.cwd())
    try:
        if archive_path.suffix in (".zip", ".whl"):
            with zipfile.ZipFile(archive_path) as zf:
                for name in zf.namelist():
                    if pattern_lower in name.lower():
                        results.append((str(archive_rel), name))
        elif archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                for member in tf.getmembers():
                    if pattern_lower in member.name.lower():
                        results.append((str(archive_rel), member.name))
        elif archive_path.name.endswith(".tar.bz2"):
            with tarfile.open(archive_path, "r:bz2") as tf:
                for member in tf.getmembers():
                    if pattern_lower in member.name.lower():
                        results.append((str(archive_rel), member.name))
        elif archive_path.name.endswith(".tar.xz"):
            with tarfile.open(archive_path, "r:xz") as tf:
                for member in tf.getmembers():
                    if pattern_lower in member.name.lower():
                        results.append((str(archive_rel), member.name))
        elif archive_path.name.endswith(".tar.7z") and py7zr:
            with py7zr.SevenZipFile(archive_path, "r") as sf:
                for name in sf.getnames():
                    if pattern_lower in name.lower():
                        results.append((str(archive_rel), name))
        elif archive_path.name.endswith(".tar.br") and brotli:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tmp:
                with open(archive_path, "rb") as f:
                    tmp.write(brotli.decompress(f.read()))
                tmp_path = tmp.name
            with tarfile.open(tmp_path, "r") as tf:
                for member in tf.getmembers():
                    if pattern_lower in member.name.lower():
                        results.append((str(archive_rel), member.name))
            Path(tmp_path).unlink()
        elif archive_path.name.endswith(".tar.zst") and zstandard:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tmp:
                dctx = zstandard.ZstdDecompressor()
                with open(archive_path, "rb") as f:
                    tmp.write(dctx.stream_reader(f).read())
                tmp_path = tmp.name
            with tarfile.open(tmp_path, "r") as tf:
                for member in tf.getmembers():
                    if pattern_lower in member.name.lower():
                        results.append((str(archive_rel), member.name))
            Path(tmp_path).unlink()
    except Exception:
        pass
    return results


def search_file(path, pattern):
    pattern_lower = pattern.lower()
    if pattern_lower in path.name.lower():
        return [(str(path.relative_to(Path.cwd())), None)]
    return []


def process_path(args):
    path, pattern = args
    if any(
        path.name.endswith(ext)
        for ext in [
            ".tar.gz",
            ".tar.xz",
            ".tar.bz2",
            ".tar.7z",
            ".tar.br",
            ".tar.zst",
            ".zip",
            ".whl",
        ]
    ):
        return search_in_archive(path, pattern)
    return search_file(path, pattern)


def search(pattern, root_dirs=None, num_workers=None):
    if root_dirs is None:
        root_dirs = [Path.cwd()]
    else:
        root_dirs = [Path(d) for d in root_dirs]
    if num_workers is None:
        num_workers = cpu_count()
    items = collect_items(root_dirs)
    work_items = [(item, pattern) for item in items]
    with Pool(num_workers) as pool:
        for results in pool.imap_unordered(process_path, work_items, chunksize=100):
            yield from results


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <pattern> [directories...]")
        sys.exit(1)
    pattern = sys.argv[1]
    root_dirs = sys.argv[2:] if len(sys.argv) > 2 else None
    for path, archive_member in search(pattern, root_dirs):
        if archive_member:
            print(f"{path}:{archive_member}")
        else:
            print(path)


if __name__ == "__main__":
    raise SystemExit(main())
