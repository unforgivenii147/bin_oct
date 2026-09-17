#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3
from PIL import Image


def process_file(path):
    path = Path(path)
    img = Image.open(path).convert("RGB")
    jpg_path = path.with_suffix(".jpg")
    img.save(jpg_path, "JPEG")
    path.unlink()
    print(f"Converted {path} to {jpg_path} and deleted the original PNG.")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".png", ".PNG"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf3(process_file, files)
