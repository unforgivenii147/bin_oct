#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from operator import itemgetter
from pathlib import Path

from dh import fsz


def get_dir_size(path: Path) -> int:
    total = 0
    for path in path.rglob("*"):
        if path.is_file() and (not path.is_symlink()):
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def du_sort_python(path: Path) -> None:
    results = []
    total = 0
    for entry in path.iterdir():
        if entry.is_dir() or entry.is_file():
            size = get_dir_size(entry) if entry.is_dir() else entry.stat().st_size
            total += size
            results.append((size, str(entry)))
    sorted_results = sorted(results, key=itemgetter(0), reverse=False)
    for size_bytes, path in sorted_results:
        sz = fsz(size_bytes)
        path = Path(path)
        if path.is_dir():
            if size_bytes > 1024 * 1024:
                print(f"\x1b[5;94m{path.name:25}\x1b[0m  \x1b[5;96m {sz}\x1b[0m")
            else:
                print(f"\x1b[5;94m{path.name:25}\x1b[0m  {sz}")
        if path.is_file():
            if size_bytes > 1024 * 1024:
                print(f"\x1b[5;92m{path.name:25}\x1b[0m  \x1b[5;96m {sz}\x1b[0m")
            else:
                print(f"\x1b[5;92m{path.name:25}\x1b[0m  {sz}")
    print(f"total size : \x1b[5;94m{fsz(total)}\x1b[0m")


if __name__ == "__main__":
    cwd = Path.cwd()
    du_sort_python(cwd)
