#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path


def get_target_folder_name(filename: str) -> str:
    if not filename:
        return "0-9"
    first_char = filename[0].lower()
    if first_char.isalpha():
        return first_char
    elif first_char.isdigit():
        return "0-9"
    else:
        return "0-9"


def cleanup_empty_dirs(root: Path) -> None:
    for dir_path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if dir_path.is_dir() and dir_path != root:
            try:
                dir_path.rmdir()
                print(f"Removed empty directory: {dir_path}")
            except OSError:
                pass


def folderize_files(root: Path = Path.cwd()) -> None:
    files_to_move = []
    for item in root.rglob("*"):
        if ".git" in item.parts:
            continue
        if item.is_file():
            files_to_move.append(item)
    if not files_to_move:
        print("No files found to organize.")
        return
    print(f"Found {len(files_to_move)} files to organize.")
    renamed_count = 0
    for path in files_to_move:
        original_name = path.name
        folder_name = get_target_folder_name(original_name)
        target_dir = root / folder_name
        target_dir.mkdir(exist_ok=True)
        target_path = target_dir / original_name
        counter = 1
        while target_path.exists():
            stem = path.stem
            suffix = path.suffix
            new_name = f"{stem}_{counter}{suffix}"
            target_path = target_dir / new_name
            counter += 1
        if target_path != path:
            shutil.move(str(path), str(target_path))
            if counter > 1:
                renamed_count += 1
                print(
                    f"Moved and renamed: {original_name} -> {target_path.name} (duplicate avoided)"
                )
            else:
                print(f"Moved: {path} -> {target_path}")
    print("\nCleaning up empty directories...")
    cleanup_empty_dirs(root)
    print("\n✓ Organization complete!")
    print(f"  - Files processed: {len(files_to_move)}")
    print(f"  - Files renamed: {renamed_count}")
    print("  - Folders created: a, b, c, ..., 0-9")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Organize files recursively into alphabetical folders"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to organize (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be moved without actually moving files",
    )
    args = parser.parse_args()
    target_dir = Path(args.directory).resolve()
    if args.dry_run:
        print(f"DRY RUN - Would organize files in: {target_dir}")
        file_count = sum(1 for _ in target_dir.rglob("*") if _.is_file())
        print(f"Would process {file_count} files")
        print("Folders would be created: a/, b/, c/, ..., 0-9/")
    else:
        print(f"Organizing files in: {target_dir}")
        folderize_files(target_dir)
