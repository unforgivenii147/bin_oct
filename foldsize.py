#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import operator
import shutil
from pathlib import Path

from loguru import logger


def get_all_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.name != "folderize.py"
    ]


def safe_rename(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        new_name = f"{stem}_{i}{suffix}"
        dest = dest_dir / new_name
        if not dest.exists():
            return dest
        i += 1


def fsz_range(min_s: int, max_s: int) -> str:
    def fmt(n: int) -> str:
        if n < 1000:
            return f"{n}B"
        if n < 1000000:
            return f"{n // 1000}k"
        return f"{n // 1000000}M"

    return f"{fmt(min_s)}-{fmt(max_s)}"


def main() -> None:
    root = Path()
    files = get_all_files(root)
    if not files:
        logger.warning("No files found to process.")
        return
    total_size = sum(f.stat().st_size for f in files)
    num_files = len(files)
    print(f"Found {num_files:,} files ({total_size:,} bytes)")
    total_size / num_files if num_files else 1
    target_files_per_dir = max(1000, int(num_files / 10))
    target_size_per_dir = max(1000000, total_size // 10)
    n_dirs_by_count = (num_files + target_files_per_dir - 1) // target_files_per_dir
    n_dirs_by_size = (total_size + target_size_per_dir - 1) // target_size_per_dir
    n_dirs = max(2, min(100, max(n_dirs_by_count, n_dirs_by_size)))
    print(f"Targeting ~{n_dirs} directories")
    files_sorted = sorted(files, key=lambda p: p.stat().st_size, reverse=True)
    dirs_info = [{"files": [], "size": 0} for _ in range(n_dirs)]
    for f in files_sorted:
        sz = f.stat().st_size
        best_idx = min(range(n_dirs), key=lambda i: dirs_info[i]["size"])
        dirs_info[best_idx]["files"].append(f)
        dirs_info[best_idx]["size"] += sz
    created_dirs = []
    existing_dir_names = {p.name for p in root.iterdir() if p.is_dir()}
    for _i, d in enumerate(dirs_info):
        if not d["files"]:
            continue
        sizes = [f.stat().st_size for f in d["files"]]
        min_s, max_s = min(sizes), max(sizes)
        dir_name = fsz_range(min_s, max_s)
        base_name = dir_name
        counter = 1
        while dir_name in existing_dir_names:
            dir_name = f"{base_name}_{counter}"
            counter += 1
        dir_path = root / dir_name
        dir_path.mkdir(exist_ok=True)
        created_dirs.append((dir_name, len(d["files"]), d["size"]))
        existing_dir_names.add(dir_name)
        print(
            f"Created dir '{dir_name}' → {len(d['files'])} files, {d['size']:,} bytes"
        )
        for f in d["files"]:
            dest = safe_rename(f, dir_path)
            shutil.move(str(f), str(dest))
    print("-" * 40)
    print("✅ Folderization complete:")
    print(f"   Files processed: {num_files:,}")
    print(f"   Directories created: {len(created_dirs)}")
    print("-" * 40)
    print(f"\n{'Dir Name':<20} {'Files':>8} {'Size (bytes)':>14}")
    print("-" * 40)
    for name, cnt, sz in sorted(created_dirs, key=operator.itemgetter(2)):
        print(f"{name:<20} {cnt:>8} {sz:>14,}")
    print(f"\nTotal directories: {len(created_dirs)}")


if __name__ == "__main__":
    raise SystemExit(main())
