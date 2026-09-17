#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    hex_color = value.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r, g, b


def hex_to_rgb_shorthand(value: str) -> tuple[int, int, int]:
    hex_color = value.lstrip("#")
    if len(hex_color) == 3:
        r = int(hex_color[0] * 2, 16)
        g = int(hex_color[1] * 2, 16)
        b = int(hex_color[2] * 2, 16)
    else:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    return r, g, b


def hex_to_rgb_dict(value: str) -> dict:
    hex_color = value.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return {"r": r, "g": g, "b": b}


if __name__ == "__main__":
    hexcolor = sys.argv[1].strip()
    print(gex_to_rgb(hexcolor))
