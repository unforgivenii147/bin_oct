#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import pydoc
import sys
from pathlib import Path


def main() -> None:
    pydoc.pager(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    raise SystemExit(main())
