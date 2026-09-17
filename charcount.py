#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import is_binary

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python count_chars_of_input_file.py <input_file>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if path.is_symlink() or is_binary(path):
        sys.exit(0)
    char_count = len(path.read_text(encoding="utf-8"))
    print(f"char : {char_count}\nsize : {path.stat().st_size}")
