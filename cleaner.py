#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys


def clean_terminal_transcript(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    ansi_escape = re.compile(
        r"\x1b(\[[0-9;]*[mABCDEFGHJKSTfhilmnprsu]|\][^\x07]*\x07|[()][AB012])"
    )
    content = ansi_escape.sub("", content)
    content = content.replace("\r\n", "\n")
    content = content.replace("\r", "\n")
    while "\x08" in content:
        content = re.sub(r".\x08", "", content)
    content = content.replace("\x00", "")
    content = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = "\n".join(line.rstrip() for line in content.splitlines())
    content = content.rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Cleaned: {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <transcript_file>")
        sys.exit(1)
    clean_terminal_transcript(sys.argv[1])
