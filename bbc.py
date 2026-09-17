#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

L1 = "[egg_info]"
L2 = "tag_build = "
L3 = "tag_date = 0"
SETUPCFG = """[egg_info]
tag_build =
tag_date = 0
"""


def is_setupcfg(fn: Path) -> bool:
    content = fn.read_text(encoding="utf8")
    if content == SETUPCFG:
        return True
    lines = content.splitlines(keepends=False)
    return bool(lines[0] == L1 and lines[1] == L2 and lines[2] == L3)


if __name__ == "__main__":
    cwd = Path.cwd()
    for item in cwd.rglob("*"):
        if item.is_dir() and item.name in ("build", "dist", "target"):
            shutil.rmtree(str(item))
            print(f"{item.name} removed.")
        if item.is_dir() and item.name.endswith("egg-info"):
            shutil.rmtree(str(item))
            print(f"{item.name} removed.")
        if item.is_file() and item.name == "PKG-INFO":
            item.unlink()
            print(f"{item.name} removed.")
        if item.is_file() and item.name == "setup.cfg" and is_setupcfg(item):
            item.unlink()
            print(f"{item.name} removed.")
