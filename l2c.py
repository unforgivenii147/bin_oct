#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def copy_line_to_clipboard(filename: str, indx) -> None:
    input_file = Path(filename)
    with input_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    content_to_copy = lines[indx].strip()
    process = subprocess.Popen(
        ["termux-clipboard-set"],
        stdin=subprocess.PIPE,
        text=True,
        stderr=subprocess.PIPE,
    )


def main() -> None:
    fn = sys.argv[1].strip()
    lindex = int(sys.argv[2].strip())
    copy_line_to_clipboard(fn, lindex)


if __name__ == "__main__":
    raise SystemExit(main())
