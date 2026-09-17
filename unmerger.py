#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_merged_file(path):
    with open(path, "r") as f:
        content = f.read()
    pattern = r"^# File: (.+?)$"
    parts = re.split(pattern, content, flags=re.MULTILINE)
    files = {}
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            path = parts[i].strip()
            file_content = parts[i + 1].lstrip("\n").rstrip()
            files[path] = file_content
    return files


def get_unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <input_file>")
        sys.exit(1)
    input_file = sys.argv[1]
    files = parse_merged_file(input_file)
    for path, file_content in files.items():
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        unique_path = get_unique_path(path)
        unique_path.write_text(file_content)
        status = "Renamed to" if unique_path.name != path.name else "Created"
        print(f"{status}: {unique_path}")


if __name__ == "__main__":
    raise SystemExit(main())
