#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

if __name__ == "__main__":
    celsius = int(sys.argv[1])
    farenheit = celsius * 9 / 5 + 32
    print(f"{farenheit:.2f}")
