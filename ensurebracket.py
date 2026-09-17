#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from collections import deque
from multiprocessing import get_context
from pathlib import Path

from dh import get_files

MAX_QUEUE = 16


def process_file(fn: Path) -> bool:
    Path(path)
    text = ""
    text = Path(fn).read_text(encoding="utf-8")
    stack = []
    mapping = {")": "(", "]": "[", "}": "{"}
    for char in text:
        if char in mapping:
            top_element = stack.pop() if stack else "#"
            if mapping[char] != top_element:
                return False
        elif char in {"(", "[", "{"}:
            stack.append(char)
    if not stack:
        print(fn.name)
    return not stack


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    with get_context("spawn").Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()


if __name__ == "__main__":
    raise SystemExit(main())
