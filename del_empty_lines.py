#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from binaryornot import is_binary
from dh import cprint


def get_filez(cwd: Path):
    for f in cwd.rglob("*"):
        if f.is_file() and not f.is_symlink():
            yield f


def process_file(path: Path) -> None:
    path = Path(path)
    removed = 0
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=False)
    newlines = []
    newlines = [line for line in lines if line.strip()]
    orig_len = len(lines)
    final_len = len(newlines)
    removed = orig_len - final_len
    if removed:
        print(f"{path.name}", end=" | ")
        cprint(f"{removed}", "blue")
        newcontent = "\n".join(newlines)
        path.write_text(newcontent, encoding="utf-8")
    else:
        print(f"{path.name}", end=" | ")
        cprint("NO CHANGE", "grey")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        files = [Path(p) for p in args]
        for f in files:
            process_file(f)
    else:
        for f in get_filez(cwd):
            if not is_binary(f):
                process_file(f)
