#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path


def get_all_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.glob("*")
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


def format_dir_name(start_idx: int, end_idx: int, total_files: int) -> str:
    return f"{start_idx}_{end_idx}"


def main() -> None:
    root = Path()
    files = get_all_files(root)
    if not files:
        logger.warning("No files found to process.")
        return
    total_files = len(files)
    print(f"Found {total_files:,} files")
    target_per_dir = max(1000, total_files // 10)
    n_dirs = max(2, (total_files + target_per_dir - 1) // target_per_dir)
    n_dirs = max(2, min(100, n_dirs))
    base_chunk = total_files // n_dirs
    remainder = total_files % n_dirs
    print(f"Creating {n_dirs} directories (~{base_chunk} files each)")
    created_dirs = []
    existing_dir_names = {p.name for p in root.iterdir() if p.is_dir()}
    for i in range(n_dirs):
        start = i * base_chunk + min(i, remainder)
        end = start + base_chunk + (1 if i < remainder else 0)
        dir_name = format_dir_name(start, end - 1, total_files)
        base_name = dir_name
        counter = 1
        while dir_name in existing_dir_names:
            dir_name = f"{base_name}_{counter}"
            counter += 1
        dir_path = root / dir_name
        dir_path.mkdir(exist_ok=True)
        created_dirs.append((dir_name, end - start))
        existing_dir_names.add(dir_name)
    print(f"Created dir '{dir_name}' for files [{start}, {end})")
    file_idx = 0
    for dir_name, count in created_dirs:
        dir_path = root / dir_name
        for _ in range(count):
            if file_idx >= total_files:
                break
            f = files[file_idx]
            dest = safe_rename(f, dir_path)
            shutil.move(str(f), str(dest))
            file_idx += 1
    print("-" * 40)
    print("✅ Folderization complete:")
    print(f"   Files processed: {total_files:,}")
    print(f"   Directories created: {len(created_dirs)}")
    print("-" * 40)
    print(f"\n{'Dir Name':<20} {'Files':>8}")
    print("-" * 40)
    for name, cnt in created_dirs:
        print(f"{name:<20} {cnt:>8}")
    print(f"\nTotal directories: {len(created_dirs)}")


if __name__ == "__main__":
    raise SystemExit(main())
