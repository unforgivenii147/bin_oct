#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import read_lines


def sort_by_length(lines: list[str], reverse: bool = False) -> list[str]:
    return sorted(lines, key=len, reverse=reverse)


if __name__ == "__main__":
    args = sys.argv[1:]
    reverse = False
    if "-r" in args:
        reverse = True
        args.remove("-r")
    if not args:
        print("Usage: python script.py [-r] <path>")
        sys.exit(1)
    path = Path(args[0].strip())
    lines = read_lines(path, ke=True)
    sorted_lines = sort_by_length(lines, reverse=reverse)
    path.write_text("".join(sorted_lines), encoding="utf8")
    print(f"{path.name} updated (reverse={reverse})")
