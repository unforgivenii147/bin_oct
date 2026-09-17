#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import pathlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial


def check_directory(dir_path, max_size_kb=None):
    try:
        contents = list(dir_path.iterdir())
        has_subdirs = any(item.is_dir() for item in contents)
        if has_subdirs:
            return None
        py_files = [
            item for item in contents if item.is_file() and item.suffix == ".py"
        ]
        if not py_files:
            return None
        if max_size_kb is not None:
            total_size = sum(f.stat().st_size for f in contents if f.is_file()) + sum(
                f.stat().st_size for f in py_files if f.is_file()
            )
            total_size_kb = total_size / 1024
            if total_size_kb > max_size_kb:
                return None
        return dir_path.name
    except (PermissionError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Find top-level directories without subdirs that contain .py files"
    )
    parser.add_argument(
        "-s",
        "--size",
        type=float,
        help="Maximum directory size in KB (e.g., -s 100 for 100KB)",
        default=None,
    )
    args = parser.parse_args()
    current_dir = pathlib.Path(".")
    dirs = [item for item in current_dir.iterdir() if item.is_dir()]
    if not dirs:
        print("No directories found in current directory.")
        return
    check_func = partial(check_directory, max_size_kb=args.size)
    matching_dirs = []
    with ProcessPoolExecutor() as executor:
        future_to_dir = {executor.submit(check_func, d): d for d in dirs}
        for future in as_completed(future_to_dir):
            result = future.result()
            if result is not None:
                matching_dirs.append(result)
    if matching_dirs:
        size_info = f" (max {args.size}KB)" if args.size else ""
        print(f"Directories without subdirs containing .py files{size_info}:")
        for dir_name in sorted(matching_dirs):
            print(f"  - {dir_name}")
        print(f"\nTotal: {len(matching_dirs)} directory(ies)")
    else:
        size_info = f" under {args.size}KB" if args.size else ""
        print(f"No matching directories found{size_info}.")


if __name__ == "__main__":
    raise SystemExit(main())
