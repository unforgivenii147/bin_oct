#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def unique_target(target: Path) -> Path:
    """
    Return a Path that does not yet exist.

    If `target` is free, it is returned unchanged. Otherwise, `_1`, `_2`, ...
    are appended to the stem until a free name is found.

    Example:
        photo.jpg      (taken)
        photo_1.jpg    (taken)
        photo_2.jpg    <- returned
    """
    # Fast path: nothing to do if the name is free.
    if not target.exists():
        return target

    # Split "photo.jpg" into stem="photo", suffix=".jpg".
    # For files with no suffix, suffix is "" and we just append _N.
    stem = target.stem
    suffix = target.suffix
    parent = target.parent

    # Try _1, _2, _3, ... until we find one that isn't taken.
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def flatten_directory(directory="."):
    """Move every file in every subdirectory (recursively) up into `directory`."""
    root = Path(directory).resolve()

    # Sanity check: the path must be an existing directory.
    if not root.is_dir():
        print(f"Error: {root} is not a valid directory")
        return

    print(f"Flattening directory: {root}")

    # Recursively gather every file found in any subdirectory at any depth.
    # rglob("*") walks the entire tree; is_file() filters out directories.
    files_to_move = [path for path in root.rglob("*") if path.is_file()]

    if not files_to_move:
        print("No files found in subdirectories.")
        return

    print(f"Found {len(files_to_move)} file(s) to move")

    moved_count = 0
    renamed_count = 0  # files moved under a _N name due to collisions

    for path in files_to_move:
        # Preferred destination: same filename, but at the root.
        target_path = root / path.name

        # Guard: if the file is already at the root it is its own target.
        # (Shouldn't normally happen since rglob only returns nested items,
        # but this keeps the logic safe if the caller changes the source set.)
        if target_path == path:
            continue

        # If the name is taken, find a free "_N" variant instead of skipping.
        if target_path.exists():
            new_target = unique_target(target_path)
            print(f"Renaming: {path.name} -> {new_target.name} (name already taken)")
            target_path = new_target
            renamed_count += 1

        try:
            shutil.move(str(path), str(target_path))
            print(f"Moved: {path} -> {target_path}")
            moved_count += 1
        except Exception as e:
            print(f"Error moving {path}: {e}")

    print(f"\nMoved {moved_count} file(s), {renamed_count} renamed due to collisions")

    # --- Cleanup: remove directories that are now empty. ---
    # Sort deepest-first so that when a child dir is removed, its parent may
    # become empty and be removable in the same pass.
    all_dirs = sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )

    removed_dirs = 0
    for subdir in all_dirs:
        try:
            # any(subdir.iterdir()) is True if there is anything left inside.
            if not any(subdir.iterdir()):
                subdir.rmdir()
                print(f"Removed empty directory: {subdir}")
                removed_dirs += 1
        except Exception as e:
            print(f"Error removing {subdir}: {e}")

    print(f"\nRemoved {removed_dirs} empty directory(ies)")
    print("Flattening complete!")


def main():
    # Optional first CLI argument: the directory to flatten (default: cwd).
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    flatten_directory(target_dir)


if __name__ == "__main__":
    main()
