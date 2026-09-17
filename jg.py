#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path


def process_dir(pardir: Path) -> bool:
    dotgit = pardir / ".git"
    if not dotgit.exists():
        return False
    for path in pardir.glob("*"):
        if path.is_dir() and path.name != ".git":
            shutil.rmtree(str(path))
        if path.is_file():
            path.unlink()
    return True


def find_targets(cwd: Path) -> None:
    for dpath in cwd.rglob("*"):
        if dpath.is_dir() and dpath.name == ".git":
            parent_of_dotgit = dpath.parent
            process_dir(parent_of_dotgit)


if __name__ == "__main__":
    cwd = Path.cwd()
    find_targets(cwd)
    for p in cwd.glob("*"):
        print(p.relative_to(cwd))
