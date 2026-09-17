#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import compileall
import sys
from collections import deque
from multiprocessing import get_context
from pathlib import Path

from dh import fsz, get_files, gsz

MAX_QUEUE = 4


def process_file(path) -> bool | None:
    path = Path(path)
    if not path.exists():
        return False
    if ".git" in path.parts:
        return None
    compileall.compile_file(path, legacy=False, optimize=0)
    return True


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    with get_context("spawn").Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    after = gsz(cwd)
    diff_size = before - after
    if after > before:
        sign = "+"
    elif before > after:
        sign = "-"
    print(f"space changed : {sign} {fsz(diff_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
