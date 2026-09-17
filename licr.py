#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import dh

EXT = [".md", ".txt", ".rst"]


def find_license_files() -> None:
    lf = []
    allfiles = dh.get_files(".")
    for file in allfiles:
        if Path(file).is_symlink():
            continue
        if Path(file).is_file():
            fn = str(dh.get_fname(file))
            ext = str(dh.get_ext(file))
            if fn.lower().startswith("license") and (ext.lower() in EXT or not ext):
                print(fn, ext)
                lf.append(file)
    print(f"Found {len(lf)} license files")
    for path in lf:
        Path(path).write_text("", encoding="utf-8")


if __name__ == "__main__":
    find_license_files()
