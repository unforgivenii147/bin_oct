#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python mdview.py <file.md>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: {path} does not exist.")
        sys.exit(1)
    console = Console()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    console.print(Markdown(content))


if __name__ == "__main__":
    main()
