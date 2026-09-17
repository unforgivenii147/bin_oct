#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from dh import get_file_age

EXCLUDED_DIRS = {".git", "__pycache__"}


def format_time(ts: float | str) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    cwd = Path.cwd()
    files = []
    opt = "-r" if len(sys.argv) > 1 else "-g"
    N = int(sys.argv[2].strip()) if len(sys.argv) > 2 else 10
    if opt == "-g":
        for p in cwd.glob("*"):
            if p.is_symlink() or any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.is_file() or p.is_dir():
                files.append(p)
    elif opt == "-r":
        for p in cwd.rglob("*"):
            if p.is_symlink() or any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.is_file():
                files.append(p)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=False)
    print(f"\nTop {N} fresh files:\n")
    for f in files[:N]:
        mtime = get_file_age(f)
        print(f"{format_time(mtime)}  -  {f.relative_to(cwd)}")


if __name__ == "__main__":
    raise SystemExit(main())
