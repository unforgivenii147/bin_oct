#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import get_files, is_binary, mpf3

cwd = Path.cwd()
bin_dir = Path(f"{cwd}/binary")
bin_dir.mkdir(exist_ok=True)


def process_file(path) -> None:
    path = Path(path)
    if is_binary(path):
        newpath = bin_dir / path.name
        path.rename(newpath)


def main() -> None:
    files = get_files(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
