#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys

if len(sys.argv) != 2:
    print("Usage: python script.py <filename>")
    sys.exit(1)
filename = sys.argv[1]
with open(filename, encoding="utf-8") as f:
    lines = [line.rstrip("\n") for line in f]
pattern = "^(?:{})$".format("|".join(re.escape(line) for line in lines))
print(pattern)
