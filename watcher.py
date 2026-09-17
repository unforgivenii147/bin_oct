#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from watchfiles import watch

if __name__ == "__main__":
    cwd = Path.cwd().resolve()
    print(f"watching {cwd} for changes ...")
    for change in watch(str(cwd)):
        print(change)
