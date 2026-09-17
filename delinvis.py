#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import string
import sys
from pathlib import Path


def find_unprintable_positions(text: str):
    allowed = set(string.printable) | {"\n", "\r", "\t"}
    positions = []
    line_num = 1
    col_num = 1
    for ch in text:
        if ch not in allowed:
            positions.append((line_num, col_num, ch, ord(ch)))
        if ch == "\n":
            line_num += 1
            col_num = 1
        else:
            col_num += 1
    return positions


def clean_text(text: str) -> str:
    allowed = set(string.printable) | {"\n", "\r", "\t"}
    return "".join(ch for ch in text if ch in allowed)


def clean_file(path: str) -> None:
    backup_path = path + ".bak"
    shutil.copy2(path, backup_path)
    data = Path(path).read_text(encoding="utf-8", errors="ignore")
    positions = find_unprintable_positions(data)
    if positions:
        print(f"Found {len(positions)} unprintable character(s):")
        for line, col, _ch, code in positions:
            print(f"  Line {line}, Col {col}: char code {code} (0x{code:02X})")
    else:
        print("No unprintable characters found.")
    cleaned = clean_text(data)
    Path(path).write_text(cleaned, encoding="utf-8", errors="ignore")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    if not Path(fname).is_file():
        print(f"Error: '{fname}' is not a file")
        sys.exit(1)
    clean_file(fname)


if __name__ == "__main__":
    raise SystemExit(main())
