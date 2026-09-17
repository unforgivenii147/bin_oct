#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def flatten_directory(directory="."):
    root = Path(directory).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a valid directory")
        return
    print(f"Flattening directory: {root}")
    files_to_move = []
    for subdir in root.iterdir():
        if subdir.is_dir():
            for path in subdir.iterdir():
                if path.is_file():
                    files_to_move.append(path)
    if not files_to_move:
        print("No files found in subdirectories.")
        return
    print(f"Found {len(files_to_move)} file(s) to move")
    moved_count = 0
    skipped_count = 0
    for path in files_to_move:
        target_path = root / path.name
        if target_path.exists():
            print(f"Skipping: {path} -> {target_path} (file already exists)")
            skipped_count += 1
            continue
        try:
            shutil.move(str(path), str(target_path))
            print(f"Moved: {path} -> {target_path}")
            moved_count += 1
        except Exception as e:
            print(f"Error moving {path}: {e}")
    print(f"\nMoved {moved_count} file(s), skipped {skipped_count} file(s)")
    removed_dirs = 0
    for subdir in root.iterdir():
        if subdir.is_dir():
            try:
                if not any(subdir.iterdir()):
                    subdir.rmdir()
                    print(f"Removed empty directory: {subdir}")
                    removed_dirs += 1
                else:
                    print(f"Directory not empty (skipping): {subdir}")
            except Exception as e:
                print(f"Error removing {subdir}: {e}")
    print(f"\nRemoved {removed_dirs} empty directory(ies)")
    print("Flattening complete!")


def main():
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    flatten_directory(target_dir)


if __name__ == "__main__":
    main()
