#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from html import unescape
from pathlib import Path


def main() -> None:
    fn = Path(sys.argv[1])
    content = fn.read_text(encoding="utf-8", errors="replace")
    fn.write_text(unescape(content), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
