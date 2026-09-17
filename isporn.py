#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import cprint, get_files, mpf3
from nudenet import NudeDetector

safe_path = Path("safe")
sexy_path = Path("sexy")
porn_path = Path("porn")
safe_path.mkdir(exist_ok=True)
sexy_path.mkdir(exist_ok=True)
porn_path.mkdir(exist_ok=True)


def check_porn(path: str):
    det = NudeDetector()
    return det.detect(path)


def process_file(path) -> None:
    path = Path(path)
    if "porn" in path.parts:
        return
    if "nude" in path.parts:
        return
    if "safr" in path.parts:
        return
    if "sexy" in path.parts:
        return
    result = check_porn(str(path))
    cprint(f"{path.name} is {result['class']} {result['score']}", "cyan")


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".jpg", ".jpeg", ".png", ".webp"])
    mpf3(process_file, files)
