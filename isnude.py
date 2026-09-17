#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import nude
from dh import cprint, get_files, mpf3

nude_path = Path("nude")
nude_path.mkdir(exist_ok=True)
RESIZE = "-r" in sys.argv


def check_nude(path: str) -> bool:
    img = cv2.imread(path)
    h, w = img.shape[:2]
    n = nude.Nude(path)
    if (h > 800 or w > 800) and RESIZE:
        n.resize(maxheight=800, maxwidth=800)
    n.parse()
    del img, h, w
    print(n)
    return bool(n.result)


def process_file(path) -> None:
    path = Path(path)
    if "nude" in path.parts:
        return
    print(f"{path.name}")
    if check_nude(str(path)):
        cprint(f"{path.name} is nude", "cyan")
        new_path = nude_path / path.name
        path.rename(new_path)


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".jpg", ".jpeg", ".png", ".webp"])
    mpf3(process_file, files)
