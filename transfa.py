#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

MAX_WORKERS: Final[int] = 4
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def translate_line(line: str) -> tuple[str, str] | None:
    if not (stripped := line.strip()):
        return None
    try:
        if not any("\u0600" <= char <= "ۿ" for char in stripped):
            return None
        translator = GoogleTranslator(source="fa", target="en")
        result = translator.translate(stripped)
        print(f"{stripped} == {result}")
        return (stripped, result) if result else None
    except Exception as e:
        logger.debug("Translation error for '%s': %s", stripped[:20], e)
        return None


def translate_file(file_input: str) -> None:
    path = Path(file_input)
    if not path.exists():
        logger.error("File not found: %s", file_input)
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.error("Error reading file: %s", e)
        return
    out_path = path.parent / f"{path.stem}_en{path.suffix}"
    print("Translating %d lines from %s...", len(lines), path.name)
    results: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_line = {executor.submit(translate_line, line): line for line in lines}
        for future in as_completed(future_to_line):
            if res := future.result():
                text, translated = res
                print("%s -> %s", text, translated)
                results.append(res)
    try:
        with out_path.open("w", encoding="utf-8") as f:
            for text, translated in results:
                f.write(f"{text} = {translated}\n")
        print("✓ Translated output saved to %s", out_path)
    except Exception as e:
        logger.error("Error writing output file: %s", e)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transfa.py <path>")
        sys.exit(1)
    translate_file(sys.argv[1])
