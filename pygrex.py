#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys

if __name__ == "__main__":
    filename = sys.argv[1]
    with open(filename, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f]
    pattern = "^(?:{})$".format("|".join(re.escape(line) for line in lines))
    print(pattern)
