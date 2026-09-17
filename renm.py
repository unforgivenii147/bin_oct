#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deep_translator import GoogleTranslator
from dh import unique_path
from fastwalk import walk_files
from tqdm import tqdm

DIRECTORY = "."
non_english_pattern = re.compile(r"[^\x00-\x7F]")


def is_english(text: str) -> bool:
    return not non_english_pattern.search(text)


translation_cache = {}


def translate_name(name):
    base, ext = os.path.splitext(name)
    if is_english(base):
        return (name, name)
    if base in translation_cache:
        return (name, translation_cache[base] + ext)
    try:
        translated = GoogleTranslator(source="auto", target="en").translate(base)
        translation_cache[base] = translated
        return (name, translated + ext)
    except Exception:
        return (name, name)


def rename_files(directory: str) -> None:
    paths = [Path(p) for p in walk_files(directory)]
    unique_names_to_translate = list({p.name for p in paths if not is_english(p.name)})
    translation_map = {}
    with ThreadPoolExecutor(8) as executor:
        futures = [
            executor.submit(translate_name, name) for name in unique_names_to_translate
        ]
        for future in tqdm(
            as_completed(futures),
            total=len(unique_names_to_translate),
            desc="Translating filenames",
        ):
            original, translated = future.result()
            translation_map[original] = translated
    for path in sorted(paths, key=lambda x: len(x.parts), reverse=True):
        if path.name not in translation_map:
            continue
        new_name = translation_map[path.name]
        if new_name == path.name:
            continue
        new_path = path.with_name(new_name)
        new_path = unique_path(new_path)
        try:
            Path(path).rename(new_path)
            print(f"Renamed: {path.name} -> {new_path.name}")
        except OSError as e:
            print(f"Error renaming {path.name}: {e}")


if __name__ == "__main__":
    rename_files(DIRECTORY)
