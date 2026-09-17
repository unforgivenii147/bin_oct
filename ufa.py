#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_nobinary, is_binary


def unicode_unescape(text: str) -> str:
    return bytes(text, "utf-8").decode("unicode_escape")


def process_file(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    path = Path(path)
    for line in lines:
        nl = r"\u" + str(line.strip())
        decoded = unicode_unescape(nl)
        print(nl)
        print(decoded)


def main() -> None:
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file() and (not is_binary(p)):
                files.append(p)
            if p.is_dir():
                files.extend(get_nobinary(p))
    else:
        files = get_nobinary(cwd)
    for f in files:
        process_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
