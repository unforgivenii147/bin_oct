#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import codecs
import shutil


def convert_in_place(filename):
    backup = f"{filename}.bak"
    shutil.copy2(filename, backup)
    with codecs.open(backup, "r", encoding="iso-8859-1") as f:
        content = f.read()
    with codecs.open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Converted {filename} (backup saved as {backup})")


if __name__ == "__main__":
    convert_in_place("script.sh")
