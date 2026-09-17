#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

import numpy as np
from PIL import Image


def get_ansi_color_code(r, g, b):
    if r == g and g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def get_color(r, g, b) -> str:
    return f"\x1b[48;5;{int(get_ansi_color_code(r, g, b))}m \x1b[0m"


def show_image(img_path: str) -> None:
    try:
        img = Image.open(img_path)
    except FileNotFoundError:
        sys.exit("Image not found.")
    h = 100
    w = int(img.width / img.height * h) * 2
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    img_arr = np.asarray(img)
    for x in range(h):
        for y in range(w):
            pix = img_arr[x][y]
            print(get_color(pix[0], pix[1], pix[2]), end="")
        print()


if __name__ == "__main__":
    show_image(sys.argv[1])
