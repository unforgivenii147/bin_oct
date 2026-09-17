#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, is_binary, mpf3, runcmd

cwd = Path.cwd()
outfile = cwd / "all_strings.txt"
all_files = 0
c = 0


def process_file(path) -> None:
    path = Path(path)
    global all_files
    global c
    c += 1
    print(f"[{c}/{all_files}] {path.name}")
    if not path.exists() or not is_binary(path):
        return
    _, txt, _ = runcmd(["strings", str(path)], show_output=False)
    with outfile.open("a", encoding="utf-8") as f:
        f.write(f"\n# filename : {path.name}\n{txt}")
    return


def main() -> None:
    args = sys.argv[1:]
    global all_files
    files = [Path(arg) for arg in args] if args else get_files(cwd)
    all_files = len(files)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
