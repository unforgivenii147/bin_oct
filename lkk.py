#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    skip_symlinks = True
    search_pattern = None
    for arg in args:
        if arg == "-s":
            skip_symlinks = False
        else:
            search_pattern = arg.strip()
    found = []
    for path in cwd.glob("*"):
        if search_pattern in path.name:
            if skip_symlinks and path.is_symlink():
                continue
            found.append(path)
    for k in sorted(found):
        if k.is_symlink():
            print(f"  - {k.name} -> {k.resolve()}")
        else:
            print(f"  - {k.name}")


if __name__ == "__main__":
    raise SystemExit(main())
