#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from pathlib import Path

from deep_translator import GoogleTranslator
from fastwalk import walk_files

DIRECTORY = "."
non_english_pattern = re.compile(r"[^\x00-\x7F]")


def translate_if_needed(name: str) -> str:
    base, ext = os.path.splitext(name)
    if not non_english_pattern.search(base):
        return name
    try:
        translated = GoogleTranslator(source="auto", target="en").translate(base)
        return translated + ext
    except Exception as e:
        print(f"Translation error for '{name}': {e}")
        return name


def get_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.stem
    ext = path.suffix
    parent = path.parent
    counter = 1
    while True:
        new_path = parent / f"{base}_{counter}{ext}"
        if not new_path.exists():
            return new_path
        counter += 1


def rename_files(directory: str) -> None:
    for pth in walk_files(directory):
        path = Path(pth)
        if path.is_file():
            new_name = translate_if_needed(path.name)
            if new_name == path.name:
                continue
            new_path = path.parent / new_name
            new_path = get_unique_path(new_path)
            Path(path).rename(new_path)
            print(f"File renamed: {path.name} -> {new_path.name}")
        elif path.is_dir():
            new_name = translate_if_needed(path.name)
            if new_name == path.name:
                continue
            new_path = path.parent / new_name
            new_path = get_unique_path(new_path)
            Path(path).rename(new_path)
            print(f"Directory renamed: {path.name} -> {new_path.name}")


if __name__ == "__main__":
    rename_files(DIRECTORY)
