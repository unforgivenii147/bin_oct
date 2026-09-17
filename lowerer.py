#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    fn = Path(sys.argv[1])
    content = fn.read_text(encoding="utf-8")
    lower_content = content.lower()
    fn.write_text(lower_content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
