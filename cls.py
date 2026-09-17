#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

if __name__ == "__main__":
    nl = []
    cwd = Path.cwd()
    for f in cwd.glob("*"):
        stm = f.stem
        if not f.is_file():
            continue
        if "-" in stm:
            indx = stm.index("-")
            nl.append(stm[:indx])
        else:
            nl.append(stm)
    for k in nl:
        print(k, end="   ")
