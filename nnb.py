#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    content = Path(fname).read_text(encoding="utf-8")
    content = content.replace("\n", "\\n")
    Path(fname).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
