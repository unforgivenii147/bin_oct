#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path

import pdfplumber
from fastwalk import walk_files


def process_file(path) -> None:
    path = Path(path)
    if path.exists() and not path.is_symlink():
        with pdfplumber.open(path) as pdf:
            numpages = len(pdf.pages)
            new_name = path.stem + str(numpages) + ".pdf"
            print(new_name)
            np = Path(f"{path.parent}/{new_name}")
            if str(numpages) in path.stem:
                return
            if not np.exists():
                Path(path).rename(np)
                print(f"{path.name} --> {np.name}")
            else:
                print(f"{np.name} exists.")
    return


def main() -> None:
    files = []
    for pth in walk_files("."):
        path = Path(pth)
        if path.is_file() and path.suffix == ".pdf":
            files.append(path)
    with get_context("spawn").Pool(8) as pool:
        for _ in pool.imap_unordered(process_file, files):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
