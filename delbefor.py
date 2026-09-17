#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import read_lines

THRESHOLD = 1048576
if __name__ == "__main__":
    file_name = Path(sys.argv[1])
    nl = []
    target_char = sys.argv[2]
    for line in read_lines(file_name):
        stripped = line.strip()
        if stripped and target_char in stripped:
            indx = stripped.index(target_char)
            cleaned = stripped[indx - 1 :]
            nl.append(cleaned)
        elif stripped:
            nl.append(stripped)
    if nl:
        file_name.write_text("\n".join(nl), encoding="utf-8")
