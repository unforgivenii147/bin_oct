#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dh import unique_path

if __name__ == "__main__":
    src = Path(sys.argv[1]).resolve()
    cwd = Path.home() / "repos"
    dst = cwd / src.name
    if dst.exists():
        dst = unique_path(dst)
    shutil.move(str(src), str(dst))
    print(f"{src.name} --> {dst.name}")
