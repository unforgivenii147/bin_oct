#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from pathlib import Path

from deep_translator import GoogleTranslator
from fastwalk import walk_files

DIRECTORY = Path.cwd()
non_english_pattern = re.compile(r"[^\x00-\x7F]")


def is_english(text: str) -> bool:
    return not non_english_pattern.search(text)


def translate_filename(filename: str):
    try:
        return GoogleTranslator(source="auto", target="en").translate(filename)
    except Exception as e:
        print(f"Translation error for {filename}: {e}")
        return filename


def rename_files(directory: str) -> None:
    for path in walk_files(directory):
        if is_english(path.stem):
            continue
        if path.is_file():
            original_path = path
            new_name = translate_filename(path.stem)
            new_path = path.with_stem(new_name)
            counter = 1
            while new_path.exists():
                name, ext = os.path.splitext(new_name)
                new_path = path.with_name(f"{name}_{counter}{ext}")
                counter += 1
            Path(original_path).rename(new_path)
            print(f"Renamed file: {original_path.name} -> {new_path.name}")
        elif path.is_dir():
            original_path = path
            new_name = translate_filename(path.name)
            new_path = path.with_name(new_name)
            counter = 1
            while new_path.exists():
                new_path = Path(f"{original_path}_{counter}")
                counter += 1
            Path(original_path).rename(new_path)
            print(f"Renamed directory: {original_path.name} -> {new_path.name}")


if __name__ == "__main__":
    rename_files(DIRECTORY)
