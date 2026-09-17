#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

EXCLUDED_DIRS = {".git", "__pycache__"}
N = 10


def format_time(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    cwd = Path.cwd()
    files = []
    opt = "-r" if len(sys.argv) > 1 else "-g"
    N = int(sys.argv[2].strip()) if len(sys.argv) > 2 else 20
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
    files.sort(key=lambda f: f.stat().st_ctime, reverse=True)
    print(f"\nTop {N} oldest files (excluding .git & __pycache__):\n")
    for f in files[:N]:
        mtime = f.stat().st_ctime
        print(f"{format_time(mtime)}  -  {f.relative_to(cwd)}")


if __name__ == "__main__":
    raise SystemExit(main())
