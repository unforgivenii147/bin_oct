#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import mpf_async, unique_path


def process_file(path) -> None:
    path = Path(path)
    if not path.exists():
        path = Path(str(path).lower())
        if not path.exists():
            return
    new_name = path.name.lower()
    if new_name == path.name:
        return
    new_path = path.with_name(new_name)
    if new_path.exists():
        new_path = unique_path(new_path)
    path.rename(new_path)
    print(f"{path.name} -> {new_path.name}")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = (
        list(cwd.glob("*"))
        if not args
        else [p for p in cwd.rglob("*") if ".git" not in p.parts and not p.is_symlink()]
    )
    mpf_async(process_file, files)
