#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import operator
from pathlib import Path


def sort_by_size(root_folder: Path):
    items = []
    for path in root_folder.glob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            size = sum(
                p.stat().st_size
                for p in path.rglob("*")
                if p.is_file() and (not p.is_symlink())
            )
        if path.is_file():
            size = path.stat().st_size
        items.append({"name": path.name, "size": size})
    items.sort(key=operator.itemgetter("size"), reverse=True)
    return items


if __name__ == "__main__":
    cwd = Path.cwd()
    data = sort_by_size(cwd)
    outfile = Path(cwd.name + ".json")
    with outfile.open("w", encoding="utf-8") as out:
        json.dump(data, out, indent=2)
