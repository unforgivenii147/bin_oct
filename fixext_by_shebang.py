#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys

SHEBANG_MAP = {
    "python": ".py",
    "python3": ".py",
    "python2": ".py",
    "bash": ".sh",
    "sh": ".sh",
    "zsh": ".sh",
    "ksh": ".sh",
    "dash": ".sh",
}
TARGET_EXTENSIONS = {".py", ".sh"}


def detect_shebang(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#!"):
                interpreter = first_line[2:].strip()
                if "/env " in interpreter:
                    interpreter = interpreter.split("/env ")[-1]
                else:
                    interpreter = os.path.basename(interpreter)
                for key, ext in SHEBANG_MAP.items():
                    if key in interpreter.lower():
                        return ext
    except OSError as e:
        print(f"Error reading {path}: {e}")
    return None


def should_rename(path, target_ext):
    current_ext = os.path.splitext(path)[1].lower()
    return current_ext != target_ext


def rename_file(path, target_ext):
    directory = os.path.dirname(path)
    basename = os.path.splitext(os.path.basename(path))[0]
    if not os.path.splitext(path)[1]:
        basename = os.path.basename(path)
    new_name = f"{basename}{target_ext}"
    new_path = os.path.join(directory, new_name)
    counter = 1
    while os.path.exists(new_path) and new_path != path:
        new_name = f"{basename}_{counter}{target_ext}"
        new_path = os.path.join(directory, new_name)
        counter += 1
    try:
        if new_path != path:
            os.rename(path, new_path)
            return new_path
    except OSError as e:
        print(f"Error renaming {path} to {new_path}: {e}")
        return None
    return None


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if dry_run:
        print("*** DRY RUN MODE - No files will be renamed ***\n")
    current_dir = os.getcwd()
    renamed_count = 0
    skipped_count = 0
    for item in os.listdir(current_dir):
        path = os.path.join(current_dir, item)
        if not os.path.isfile(path):
            continue
        target_ext = detect_shebang(path)
        if target_ext is None:
            if verbose:
                print(f"  SKIP: {item} (no recognized shebang)")
            continue
        if not should_rename(path, target_ext):
            if verbose:
                print(f"  SKIP: {item} (already has correct extension)")
            skipped_count += 1
            continue
        if dry_run:
            new_name = os.path.splitext(item)[0] + target_ext
            print(f"  WOULD RENAME: {item} -> {new_name}")
            renamed_count += 1
        else:
            result = rename_file(path, target_ext)
            if result:
                print(f"  RENAMED: {item} -> {os.path.basename(result)}")
                renamed_count += 1
            else:
                skipped_count += 1
    print("\nSummary:")
    if dry_run:
        print(f"  Would rename: {renamed_count} files")
    else:
        print(f"  Renamed: {renamed_count} files")
    print(f"  Skipped: {skipped_count} files")


if __name__ == "__main__":
    raise SystemExit(main())
