#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import sys
import zipfile


def find_whl_files(directory):
    whl_files = []
    for root, _dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".whl"):
                whl_files.append(os.path.join(root, file))
    return whl_files


def check_entry_points(whl_path):
    try:
        with zipfile.ZipFile(whl_path, "r") as whl:
            for file_info in whl.filelist:
                if file_info.filename.endswith("entry_points.txt"):
                    dist_info_dir = os.path.dirname(file_info.filename)
                    return True, dist_info_dir
            return False, None
    except zipfile.BadZipFile:
        return False, None
    except Exception as e:
        print(f"Error reading {whl_path}: {e}", file=sys.stderr)
        return False, None


def get_whl_info(whl_path):
    basename = os.path.basename(whl_path)
    parts = basename.split("-")
    if len(parts) >= 3:
        name = parts[0]
        version = parts[1]
        return name, version
    return basename, "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Find .whl files that contain entry_points.txt"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to search for .whl files (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose output with all files checked",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show files with entry_points.txt",
    )
    args = parser.parse_args()
    directory = args.directory
    if not os.path.exists(directory):
        print(f"Error: Directory '{directory}' not found", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        sys.exit(1)
    whl_files = find_whl_files(directory)
    if not whl_files:
        print(f"No .whl files found in '{directory}'")
        return
    print(f"Checking {len(whl_files)} .whl file(s) in '{directory}'...\n")
    has_entry_points = []
    no_entry_points = []
    errors = []
    for whl_path in whl_files:
        name, version = get_whl_info(whl_path)
        has, dist_info = check_entry_points(whl_path)
        if has:
            has_entry_points.append((whl_path, name, version, dist_info))
        elif has is False and dist_info is None:
            no_entry_points.append((whl_path, name, version))
        else:
            errors.append(whl_path)
    if has_entry_points:
        print("-" * 40)
        print(f"✅ Found {len(has_entry_points)} wheel(s) with entry_points.txt:")
        print("-" * 40)
        for whl_path, name, version, dist_info in has_entry_points:
            print(f"\n📦 {name} ({version})")
            print(f"   File: {whl_path}")
            print(f"   Dist-info: {dist_info}")
    else:
        print("❌ No wheels found with entry_points.txt")
    if not args.quiet and no_entry_points:
        print("\n" + "=" * 40)
        print(f"📋 {len(no_entry_points)} wheel(s) WITHOUT entry_points.txt:")
        print("-" * 40)
        if args.verbose:
            for whl_path, name, version in no_entry_points:
                print(f"   {name} ({version}): {whl_path}")
        else:
            print("   (Use -v to see full list)")
    if errors:
        print("\n" + "=" * 40)
        print(f"⚠️  {len(errors)} wheel(s) could not be read:")
        print("-" * 40)
        for whl_path in errors:
            print(f"   {whl_path}")
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total wheels checked:  {len(whl_files)}")
    print(f"With entry_points.txt: {len(has_entry_points)}")
    print(f"Without:               {len(no_entry_points)}")
    if errors:
        print(f"Errors:                {len(errors)}")


if __name__ == "__main__":
    raise SystemExit(main())
