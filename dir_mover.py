#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path
from shutil import move


def validate_dirs(source: Path, dest: Path) -> bool:
    if not source.is_dir():
        print(f"❌ Source directory does not exist: {source}")
        return False
    if not dest.is_dir():
        print(f"❌ Destination directory does not exist: {dest}")
        return False
    if source == dest:
        print("❌ Source and destination cannot be the same directory")
        return False
    return True


def get_top_level_subdirs(directory: Path) -> list[Path]:
    subdirs = [p for p in directory.iterdir() if p.is_dir()]
    return sorted(subdirs)


def move_subdirs(source: Path, dest: Path) -> None:
    print(f"📂 Source directory: {source.resolve()}")
    print(f"📂 Destination directory: {dest.resolve()}")
    print("-" * 40)
    source_subdirs = get_top_level_subdirs(source)
    if not source_subdirs:
        print("⚠️  No subdirectories found in source")
        return
    dest_subdir_names = {p.name for p in get_top_level_subdirs(dest)}
    moved = []
    skipped = []
    for subdir in source_subdirs:
        if subdir.name in dest_subdir_names:
            print(f"⏭️  SKIP: {subdir.name} (already exists in destination)")
            skipped.append(subdir.name)
        else:
            try:
                new_path = dest / subdir.name
                print(f"➡️  MOVE: {subdir.name}")
                print(f"   From: {subdir.resolve()}")
                print(f"   To:   {new_path.resolve()}")
                move(str(subdir), str(new_path))
                moved.append(subdir.name)
                print(f"   ✅ Success")
            except Exception as e:
                print(f"   ❌ Error: {e}")
    print("-" * 40)
    print(f"\n📊 Summary:")
    print(f"✅ Moved: {len(moved)}")
    if moved:
        for name in moved:
            print(f"   • {name}")
    print(f"⏭️  Skipped: {len(skipped)}")
    if skipped:
        for name in skipped:
            print(f"   • {name}")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python dir_mver.py <source_dir> <dest_dir>")
        print("Example: python dir_mver.py ~/repos/projects ~/isaac")
        sys.exit(1)
    source = Path(sys.argv[1]).expanduser().resolve()
    dest = Path(sys.argv[2]).expanduser().resolve()
    if not validate_dirs(source, dest):
        sys.exit(1)
    move_subdirs(source, dest)


if __name__ == "__main__":
    raise SystemExit(main())
