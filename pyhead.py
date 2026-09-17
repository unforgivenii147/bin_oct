#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    fn = Path(sys.argv[1])
    try:
        with fn.open(encoding="utf-8", errors="ignore") as f:
            print(f.read(1024))
    except:
        with fn.open("rb") as f:
            print(f.read(1024))
