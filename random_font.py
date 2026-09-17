#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import secrets
from pathlib import Path


def convert_with_fonttools(src, dst):
    from fontTools.ttLib import woff2

    try:
        woff2.decompress(src, dst)
    except Exception as e:
        return


def main():
    source_dir = Path("/sdcard/font")
    dst = Path.home() / ".termux" / "font.ttf"
    if dst.exists():
        dst.unlink()
    files = [
        p
        for p in source_dir.glob("*.woff2")
        if "italic" not in p.name and p.stat().st_size > 400_000
    ]
    numfiles = len(files)
    indx = secrets.randbelow(numfiles)
    src = files[indx]
    print(f"{indx}/{numfiles} -> {src.name} selected")
    ttf_path = src.with_suffix(".ttf")
    if ttf_path.exists():
        ttf_path.rename(dst)


if __name__ == "__main__":
    raise SystemExit(main())
