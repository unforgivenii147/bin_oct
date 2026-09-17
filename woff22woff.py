#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, get_files, mpf3, unique_path
from fontTools.ttLib import TTFont

cwd = Path.cwd()


def process_file(path: Path) -> None:
    path = Path(path)
    woff_path = path.with_suffix(".woff")
    if woff_path.exists() and woff_path.stat().st_size:
        woff_path = unique_path(woff_path)
    try:
        font = TTFont(path)
        font.flavor = "woff"
        font.save(woff_path)
        print(f"{path.name} converted.")
        path.unlink()
    except:
        cprint(f"error convering {path.name}")


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".ttf", ".otf"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
