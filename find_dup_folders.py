#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from dh import get_dirs
from xxhash import xxh64

CHUNK_SIZE = 1024 * 1024


def is_nested(path1: Path, path2: Path) -> bool:
    try:
        path1.resolve().relative_to(path2.resolve())
        return True
    except ValueError:
        pass
    try:
        path2.resolve().relative_to(path1.resolve())
        return True
    except ValueError:
        pass
    return False


def hash_folder(folder_path: Path) -> str:
    hasher = xxh64()
    files = []
    for path in folder_path.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
    if not files:
        return ""
    for file in sorted(files):
        rel = file.relative_to(folder_path)
        hasher.update(str(rel).encode("utf-8"))
        try:
            with file.open("rb") as f:
                while chunk := f.read(CHUNK_SIZE):
                    hasher.update(chunk)
        except OSError:
            continue
    return hasher.hexdigest()


def find_duplicate_folders(cwd: Path):
    folder_hashes = defaultdict(list)
    for path in get_dirs(cwd):
        if ".git" in path.parts:
            continue
        folder_hash = hash_folder(path)
        if folder_hash:
            folder_hashes.setdefault(folder_hash, []).append(path)
    return {h: paths for h, paths in folder_hashes.items() if len(paths) > 1}


if __name__ == "__main__":
    cwd = Path.cwd()
    duplicates = find_duplicate_folders(cwd)
    if duplicates:
        print("Duplicate folder groups:")
        for h, paths in duplicates.items():
            print(f"\nGroup (Hash: {h}):")
            for path in paths:
                print(f"  - {path}")
        cleaned = defaultdict(list)
        for h, paths in duplicates.items():
            for i in range(len(paths)):
                for j in range(i + 1, len(paths)):
                    p1 = Path(paths[i])
                    p2 = Path(paths[j])
                    if not is_nested(p1, p2):
                        cleaned[h].append(str(p1))
        with Path("/sdcard/dupdirs.json").open("w", encoding="utf-8") as fo:
            json.dump(cleaned, fo)
    else:
        print("No duplicate folders found.")
