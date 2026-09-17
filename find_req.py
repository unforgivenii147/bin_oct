#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def process_file(path: Path, text: str) -> None:
    path = Path(path)
    content = path.read_text().lower()
    target1 = "requires-dist: " + text
    if target1 in content:
        print(path.parent.name)


if __name__ == "__main__":
    cwd = Path("/data/data/com.termux/files/home/.local/lib/python3.12/site-packages")
    target = sys.argv[1]
    for path in cwd.rglob("METADATA"):
        process_file(path, target)
