#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

if __name__ == "__main__":
    cwd = Path.cwd()
    for path in cwd.glob("*"):
        if path.is_dir():
            print(f"  -  {path.name}")
