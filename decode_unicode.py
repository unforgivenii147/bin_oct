#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__":
    path = Path(sys.argv[1].strip())
    text = path.read_bytes()
    decoded = text.encode("utf-8").decode("unicode_escape")
    path.write_text(decoded, encoding="utf-8")
    print(f"{path} updated")
