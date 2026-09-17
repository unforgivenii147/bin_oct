#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def split_file_by_delimiter(fname: str, delimiter: str) -> None:
    content = Path(fname).read_text(encoding="utf-8")
    parts = content.split(delimiter)
    with Path(fname).open("w", encoding="utf-8") as f:
        f.writelines(part.strip() + f"{delimiter}\n" for part in parts)


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python script.py <filename> <delimiter>")
        sys.exit(1)
    fname = sys.argv[1]
    delimiter = sys.argv[2]
    if not delimiter:
        print("Error: delimiter cannot be empty")
        sys.exit(1)
    split_file_by_delimiter(fname, delimiter)
    print(f"{sys.argv[1]} updated.")


if __name__ == "__main__":
    raise SystemExit(main())
