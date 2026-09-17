#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

if __name__ == "__main__":
    cwd = Path.cwd()
    for r, _d, files in cwd.walk():
        for file in files:
            path = Path(r) / file
            if path.is_file() and path.name.endswith(".bak"):
                print(path.relative_to(cwd))
                path.unlink()
