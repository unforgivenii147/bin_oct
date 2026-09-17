#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    fn = Path(sys.argv[1])
    content = fn.read_text(encoding="utf-8")
    lines = content.splitlines()
    lowest = "480" if "480" in content else "720"
    nl = [
        line
        for line in lines
        if line.strip() and ("mkv" in line or "mp4" in line) and (lowest in line)
    ]
    if nl:
        fn.write_text("\n".join(nl), encoding="utf-8")
    print(f"{len(nl)} links found.")
