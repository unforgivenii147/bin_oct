#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

from dh import fsz, gsz


def clean_pycache(start_dir: Path = Path.cwd()) -> None:
    removed = 0
    sz = 0
    for path in start_dir.rglob("__pycache__"):
        if path.exists():
            sz += gsz(path)
            removed += 1
            shutil.rmtree(str(path))
    if removed:
        print(f"   • Total size freed: {fsz(sz)}")
        print(f"   • dirs removed: {removed}")
    else:
        print("nothing found.")


if __name__ == "__main__":
    cwd = Path.cwd()
    clean_pycache(cwd)
