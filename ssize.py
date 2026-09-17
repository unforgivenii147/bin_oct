#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import operator
from pathlib import Path

from dh import fsz, gsz

total = 0


def list_and_sort_by_size(path: Path = Path()):
    items = []
    global total
    for p in path.glob("*"):
        if p.is_symlink():
            continue
        size = gsz(p)
        total += size
        items.append({"name": p.name, "size": size})
    items.sort(key=operator.itemgetter("size"), reverse=False)
    return items


if __name__ == "__main__":
    data = list_and_sort_by_size()
    for k in data:
        print(f"{k['name']} : \x1b[5;96m {fsz(k['size'])}\x1b[0m")
    print(f"\ntotal:\x1b[5;94m {fsz(total)}\x1b[0m")
