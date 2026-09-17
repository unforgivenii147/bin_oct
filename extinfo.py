#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import fsz


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: script.py <extension>")
        print("Example: script.py py")
        sys.exit(1)
    ext = sys.argv[1].lstrip(".")
    cwd = Path.cwd()
    files = list(cwd.rglob(f"*.{ext}"))
    if not files:
        print(f"No .{ext} files found in current directory")
        sys.exit(0)
    total_size = sum(f.stat().st_size for f in files)
    count = len(files)
    print(f"Total number of .{ext} files: {count}")
    print(f"Total size of .{ext} files: {fsz(total_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
