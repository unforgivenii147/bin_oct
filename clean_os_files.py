#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os

WINDOWS_FILES = {".exe", ".dll", ".bat", ".com", ".msi", ".vbs", ".ps1"}
MACOS_FILES = {".dmg", ".app", ".DS_Store", ".plist", ".pkg"}


def find_target_files(root_dir):
    target_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if (
                any(filename.lower().endswith(ext) for ext in WINDOWS_FILES)
                or any(filename.lower().endswith(ext) for ext in MACOS_FILES)
                or filename == ".DS_Store"
            ):
                target_files.append(os.path.join(dirpath, filename))
    return target_files


def main():
    parser = argparse.ArgumentParser(
        description="Search for Windows/macOS files in the current directory and optionally remove them."
    )
    parser.add_argument(
        "-a",
        "--auto-remove",
        action="store_true",
        help="Automatically remove found files after confirmation.",
    )
    args = parser.parse_args()
    current_dir = os.getcwd()
    print(f"Scanning directory: {current_dir}\n")
    found_files = find_target_files(current_dir)
    if not found_files:
        print("No Windows or macOS related files found.")
        return
    cwd = Path.cwd().resolve()
    print(f"Found {len(found_files)} file(s):\n")
    for path in found_files:
        print(f"  {path.relative_to(cwd)}")
    if args.auto_remove:
        print("\n" + "=" * 35)
        deleted_count = 0
        for path in found_files:
            try:
                os.remove(path)
                print(f"Deleted: {path}")
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {path}: {e}")
        print(f"\nDeleted {deleted_count} of {len(found_files)} files.")


if __name__ == "__main__":
    raise SystemExit(main())
