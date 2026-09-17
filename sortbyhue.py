#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path

HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def hex_to_hsv(hex_color: str) -> tuple[float, float, float]:
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    return colorsys.rgb_to_hsv(r, g, b)


def sort_key(color: str) -> tuple[float, float, float]:
    h, s, v = hex_to_hsv(color)
    return h, s, v


def main(path: str) -> None:
    with Path(path).open(encoding="utf-8") as f:
        colors = [line.strip() for line in f if HEX_RE.match(line.strip())]
    colors.sort(key=sort_key)
    with Path(path).open("w", encoding="utf-8") as f:
        f.writelines(c.lower() + "\n" for c in colors)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: sort_colors.py colors.txt")
        sys.exit(1)
    main(sys.argv[1])
