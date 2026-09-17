#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from faprint import faprint as pp


def ylines(path: Path):
    with path.open(encoding="utf-8") as f:
        yield from f


if __name__ == "__main__":
    fn = Path(sys.argv[1])
    for k in ylines(fn):
        print(pp(k))
