#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def dict_val(line: str) -> str:
    if ":" in line:
        out = line.split(":", 1)[1].strip()
        print(out)
        return out
    if "=" in line:
        out = line.split("=", 1)[1].strip()
        print(out)
        return out
    return line


def main() -> None:
    fname = sys.argv[1]
    with Path(fname).open(encoding="utf8", errors="replace") as f:
        lines = f.readlines()
    all_lines = [line for line in lines if ":" in line or "=" in line]
    all_lines.sort(key=dict_val)
    with Path(fname).open("w", encoding="utf-8") as fo:
        fo.writelines(all_lines)


if __name__ == "__main__":
    raise SystemExit(main())
