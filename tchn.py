#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deep_translator import GoogleTranslator

DIRECTORY = "."
CHUNK_SIZE = 2000
non_english_pattern = re.compile(r"[^\x00-\x7F]")


def is_text_file(path: Path) -> bool:
    try:
        with Path(path).open("rb") as f:
            chunk = f.read(2048)
        return b"\x00" not in chunk
    except:
        return False


def split_into_chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    try:
        return GoogleTranslator(source="auto", target="en").translate(chunk)
    except Exception as e:
        print(f"Chunk translation error: {e}")
        return chunk


def translate_file(path: Path) -> None:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except:
        print(f"Skipping unreadable file: {path}")
        return
    if not non_english_pattern.search(content):
        return
    chunks = split_into_chunks(content, 32768)
    with ThreadPoolExecutor(max_workers=8) as executor:
        translated_chunks = list(executor.map(translate_chunk, chunks))
    translated_text = "".join(translated_chunks)
    new_name = f"{path.stem}_eng{path.suffix}"
    new_path = path.parent / new_name
    try:
        Path(new_path).write_text(translated_text, encoding="utf-8")
        print(f"Translated → {new_path.name}")
    except Exception as e:
        print(f"Error writing {new_path}: {e}")


def process_directory(directory: str) -> None:
    files = []
    for path in walker(directory):
        if path.is_file() and is_text_file(path):
            files.append(path)
    print(f"Found {len(files)} text files to process")
    with ThreadPoolExecutor(8) as executor:
        futures = {executor.submit(translate_file, f): f for f in files}
        for future in as_completed(futures):
            f = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Error processing {f}: {e}")


if __name__ == "__main__":
    process_directory(DIRECTORY)
