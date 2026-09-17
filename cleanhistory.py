#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

if __name__ == "__main__":
    fn = Path.home() / ".bash_history"
    nl = []
    with fn.open(encoding="utf-8") as f:
        nl.extend(line for line in f if 'cd "`printf' not in line)
    nl = list(set(nl))
    with fn.open("w", encoding="utf-8") as fo:
        fo.writelines(nl)
    print("done.")
