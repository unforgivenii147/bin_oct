#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import operator
import os
import stat
import sys
from pathlib import Path

from dh import fsz, gsz

CYAN = "\x1b[36m"
BLUE = "\x1b[34m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
RESET = "\x1b[0m"
COMPRESSED_EXTS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z"}


def list_dir(path: str = ".") -> None:
    entries = os.listdir(path)
    items = []
    for entry in entries:
        full_path = os.path.join(path, entry)
        try:
            if Path(full_path).is_dir():
                size = gsz(full_path)
                color = BLUE
            else:
                size = Path(full_path).stat().st_size
                mode = os.stat(full_path).st_mode
                ext = os.path.splitext(entry)[1].lower()
                if ext in COMPRESSED_EXTS:
                    color = RED
                elif mode & stat.S_IXUSR:
                    color = GREEN
                else:
                    color = CYAN
        except Exception:
            size = 0
            color = CYAN
        items.append((size, entry, color))
    size_col_width = max(len(fsz(s)) for s, _, _ in items)
    name_col_width = max(len(n) for _, n, _ in items)
    print(f"{'size'.ljust(size_col_width)}  {'name'}")
    print("-" * (size_col_width + name_col_width + 2))
    for size, name, color in sorted(items, key=operator.itemgetter(0)):
        size_str = fsz(size).ljust(size_col_width)
        print(f"{size_str}  {color}{name}{RESET}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        list_dir(sys.argv[1])
    else:
        list_dir(".")
