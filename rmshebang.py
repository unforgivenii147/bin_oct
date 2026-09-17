#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from collections import deque
from multiprocessing import get_context
from pathlib import Path

from dh import fsz, get_files, gsz

MAX_QUEUE = 16


def process_file(path) -> None:
    path = Path(path)
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        if lines[0].startswith("#!/"):
            new_lines = lines[1:]
            content = "\n".join(new_lines)
            path.write_text(content, encoding="utf-8")
            print(f"{path.name} updated.")
            return
        return
    except Exception:
        pass


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(cwd, ext=[".py"])
    with get_context("spawn").Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    diffsize = before - gsz(cwd)
    print(f"space saved: {fsz(diffsize)}")


if __name__ == "__main__":
    raise SystemExit(main())
