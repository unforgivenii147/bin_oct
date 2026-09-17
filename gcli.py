#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from googlesearch import search

if __name__ == "__main__":
    tts = sys.argv[1]
    for result in search(tts):
        print(result)
