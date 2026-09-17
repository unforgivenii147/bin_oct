#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from os import chdir as os_chdir
from pathlib import Path

from dh import get_files, mpf3, runcmd


def process_file(path_str: str) -> None:
    path = Path(path_str)
    os_chdir(path.parent)
    cmd = ["python", "setup.py", "bdist_wheel"]
    ret, _, _ = runcmd(cmd)
    if ret != 0:
        print(f"Error building wheel for {path}")


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd)
    targets = [str(path) for path in files if path.name == "setup.py"]
    mpf3(process_file, targets)
    whl_files = get_files(cwd, ext=[".whl"])
    if whl_files:
        for k in whl_files:
            print(k)
