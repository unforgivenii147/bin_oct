#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import pydoc
import sys
from pathlib import Path

README_CANDIDATES = ["README.md", "README.rst", "README.txt", "README"]


def find_readme() -> Path | None:
    files = {p.name.lower(): p for p in Path().iterdir() if p.is_file()}
    for name in README_CANDIDATES:
        p = files.get(name.lower())
        if p:
            return p
    return None


def main() -> None:
    readme = find_readme()
    if not readme:
        print("No README file found in current directory.", file=sys.stderr)
        sys.exit(1)
    try:
        text = readme.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = readme.read_text(errors="replace")
    pydoc.pager(text)


if __name__ == "__main__":
    raise SystemExit(main())
