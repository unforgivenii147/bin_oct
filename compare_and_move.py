#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def expand_path(path_str: str) -> Path:
    expanded = Path(path_str).expandvars()
    return Path(expanded).expanduser().resolve()


def compare_and_move_common(source_dir: str, target_dir: str) -> None:
    source = expand_path(source_dir)
    target = expand_path(target_dir)
    print(f"Source directory (first): {source}")
    print(f"Target directory (second): {target}")
    print("-" * 40)
    if not source.exists():
        print(
            f"Error: Source directory '{source_dir}' (expanded to '{source}') does not exist."
        )
        return
    if not target.exists():
        print(
            f"Error: Target directory '{target_dir}' (expanded to '{target}') does not exist."
        )
        return
    common_dir = Path.cwd() / "common"
    common_dir.mkdir(exist_ok=True)
    print(f"Created/verified directory: {common_dir}")
    source_files = {f.name for f in source.iterdir() if f.is_file()}
    target_files = {f.name for f in target.iterdir() if f.is_file()}
    common_files = source_files & target_files
    if not common_files:
        print("\nNo files found that exist in both directories.")
        return
    print(f"\nFound {len(common_files)} file(s) that exist in BOTH directories:")
    for filename in sorted(common_files):
        source_size = (source / filename).stat().st_size
        target_size = (target / filename).stat().st_size
        size_match = "✓" if source_size == target_size else "⚠"
        print(
            f"  {size_match} {filename} (source: {source_size} bytes, target: {target_size} bytes)"
        )
    print("\n" + "=" * 40)
    response = input(
        f"Move these {len(common_files)} common file(s) from source to '{common_dir}'? (y/n): "
    ).lower()
    if response != "y":
        print("Operation cancelled.")
        return
    moved_count = 0
    failed_files = []
    size_mismatches = []
    for filename in sorted(common_files):
        source_path = source / filename
        dest_path = common_dir / filename
        target_path = target / filename
        if source_path.stat().st_size != target_path.stat().st_size:
            size_mismatches.append(filename)
        if dest_path.exists():
            base = dest_path.stem
            ext = dest_path.suffix
            counter = 1
            while dest_path.exists():
                new_name = f"{base}_common{counter}{ext}"
                dest_path = common_dir / new_name
                counter += 1
            print(
                f"\n  Note: '{filename}' will be renamed to '{dest_path.name}' to avoid conflict"
            )
        try:
            shutil.move(source_path, dest_path)
            print(f"  ✓ Moved: {filename} -> {dest_path.name}")
            moved_count += 1
        except Exception as e:
            print(f"  ✗ Error moving {filename}: {e}")
            failed_files.append(filename)
    print("\n" + "=" * 40)
    print(
        f"Summary: Successfully moved {moved_count} of {len(common_files)} common file(s)"
    )
    if size_mismatches:
        print(
            f"\n⚠ Warning: {len(size_mismatches)} file(s) had different sizes in source vs target:"
        )
        for filename in size_mismatches:
            print(f"  - {filename}")
        print("  (Files were still moved, but verify they are correct versions)")
    if failed_files:
        print(f"\nFailed to move {len(failed_files)} file(s):")
        for filename in failed_files:
            print(f"  - {filename}")
    if moved_count > 0:
        print(f"\nMoved common files are located in: {common_dir}")
        print(f"Note: These files still exist in the target directory: {target}")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python compare_dirs.py <source_directory> <target_directory>")
        print("\nWhat this script does:")
        print("  Moves files that exist in BOTH directories from the source directory")
        print("  to a 'common' folder in the current working directory.")
        print("\nExamples:")
        print("  python compare_dirs.py ~/Documents/dir1 /absolute/path/to/dir2")
        print("  python compare_dirs.py ./first_dir ../second_dir")
        print("  python compare_dirs.py $HOME/data1 $PROJECT/data2")
        sys.exit(1)
    source_dir = sys.argv[1]
    target_dir = sys.argv[2]
    compare_and_move_common(source_dir, target_dir)


if __name__ == "__main__":
    raise SystemExit(main())
