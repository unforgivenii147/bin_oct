#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def get_common_lines(file1_path: str, file2_path: str):
    path1 = Path(file1_path)
    path2 = Path(file2_path)
    if not path1.exists() or not path2.exists():
        print("Error: One or both files do not exist.")
        sys.exit(1)
    with path1.open("r", encoding="utf-8") as f1:
        lines1 = {line.strip("\n") for line in f1}
    common = []
    seen = set()
    with path2.open("r", encoding="utf-8") as f2:
        for line in f2:
            clean_line = line.strip("\n")
            if clean_line in lines1 and clean_line not in seen:
                common.append(clean_line)
                seen.add(clean_line)
                print(clean_line)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script.py <file1> <file2>")
        sys.exit(1)
    get_common_lines(sys.argv[1], sys.argv[2])
