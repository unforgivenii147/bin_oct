#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def file_hash(path: Path, block_size=65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def build_hash_map(root_path: Path):
    hash_map = {}
    for item in root_path.rglob("*"):
        if item.is_file():
            rel = item.relative_to(root_path)
            hash_map[str(rel)] = file_hash(item)
    return hash_map


def compare_dirs(dir1_str: str, dir2_str: str) -> None:
    dir1 = Path(dir1_str)
    dir2 = Path(dir2_str)
    map1 = build_hash_map(dir1)
    map2 = build_hash_map(dir2)
    changed = []
    common = []
    only_in_dir1 = []
    for rel_path, h1 in map1.items():
        if rel_path not in map2:
            only_in_dir1.append(rel_path)
        elif h1 == map2[rel_path]:
            common.append(rel_path)
        else:
            changed.append(rel_path)
    Path("dir1.txt").write_text("\n".join(changed), encoding="utf-8")
    Path("common.txt").write_text("\n".join(common), encoding="utf-8")
    Path("only_in_dir1.txt").write_text("\n".join(only_in_dir1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python compare_dirz.py <dir1> <dir2>")
        sys.exit(1)
    DIR1 = sys.argv[1]
    DIR2 = sys.argv[2]
    compare_dirs(DIR1, DIR2)
    print("Comparison complete. See dir1.txt, common.txt, only_in_dir1.txt")
