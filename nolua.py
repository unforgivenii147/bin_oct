#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import get_files


def has_lua(root_dir):
    lua_files = []
    lua_files = get_files(root_dir, ext=[".lua"])
    return bool(lua_files)


def move_to_start(src):
    dest = "/data/data/com.termux/files/home/.vim/pack/plugins/start"
    if not Path(dest).exists():
        Path(dest).mkdir(exist_ok=True)
    import shutil

    target_path = f"{dest}/{src.name}"
    shutil.copytree(str(src), target_path)
    shutil.rmtree(src)


if __name__ == "__main__":
    cwd = Path.cwd()
    for dirpath in cwd.iterdir():
        if not dirpath.is_dir():
            continue
        if not has_lua(dirpath):
            print(f" - {dirpath.name}")
