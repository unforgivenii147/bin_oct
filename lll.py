#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import datetime
from pathlib import Path

from dh import fsz, gsz

EXCLUDED = {".mypy_cache", ".ruff_cache", ".git", "__pycache__"}
if __name__ == "__main__":
    cwd = Path.cwd()
    for path in sorted(cwd.rglob("*"), key=lambda e: e.stat().st_mtime, reverse=True):
        if any(pat in path.parts for pat in EXCLUDED):
            continue
        mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")
        if path.is_dir():
            continue
        elif path.is_symlink():
            sz = " \x1b[05;95msymlink "
        else:
            sz = str(fsz(gsz(path)))
            if len(sz) == 7:
                sz = "  " + sz
            if len(sz) == 8:
                sz = " " + sz
        if path.is_symlink():
            print(f"\x1b[05;95m{path.name[:24]:25}\x1b[0m", end=" ")
        else:
            print(f"\x1b[05;94m{path.name[:24]:25}\x1b[0m", end=" ")
        print(f"\x1b[05;96m{sz}\x1b[0m", end=" ")
        print(f"\x1b[05;93m{mtime}\x1b[0m")
