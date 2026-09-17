#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3
from PIL import Image, ImageEnhance


def process_file(path):
    path = Path(path)
    try:
        with Image.open(path) as img:
            ce = ImageEnhance.Contrast(img)
            be = ImageEnhance.Brightness(img)
            se = ImageEnhance.Sharpness(img)
            cce = ImageEnhance.Color(img)
            img = ce.enhance(1.1)
            img = be.enhance(1.1)
            img = se.enhance(1.1)
            img = cce.enhance(1.1)
            img.save(path)
            print(f"Enhanced: {path.name}")
    except Exception as e:
        print(f"Error enhancing {path.name}: {e}")


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p, ext=[".jpg", ".png", ".webp"]))
    else:
        files = get_files(cwd, ext=[".jpg", ".png", ".webp"])
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
