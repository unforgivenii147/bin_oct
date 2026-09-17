#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import cv2
from dh import get_files


def process_file(path) -> None:
    path_str = str(path)
    img = cv2.imread(path_str)
    if not img.any():
        return
    h, w = img.shape[:2]
    if 1 < w < 200:
        FACTOR = 8
    elif 200 <= w <= 500:
        FACTOR = 6
    elif 500 <= w <= 1000:
        FACTOR = 4
    elif 1000 <= w <= 2000:
        FACTOR = 2
    elif w > 2000:
        del w, h, img
        return
    print(f"[✓] {path.name}:{h}X{w} -> {h * FACTOR}X{w * FACTOR}")
    try:
        resized = cv2.resize(
            img, (w * FACTOR, h * FACTOR), interpolation=cv2.INTER_LANCZOS4
        )
        del img, h, w
        sharpened = cv2.addWeighted(resized, 1.5, resized, -0.5, 0)
        del resized
        cv2.imwrite(path, sharpened)
        del sharpened
        return
    except:
        return


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = (
        [Path(p) for p in args]
        if args
        else get_files(cwd, ext=[".webp", ".jpg", ".jpeg", ".png"])
    )
    for c, f in enumerate(files):
        print(f"{c}/{len(files)}")
        process_file(f)
