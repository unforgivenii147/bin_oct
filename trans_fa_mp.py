#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

MAX_WORKERS: Final[int] = 16
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def translate_word(word: str) -> str | None:
    translator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result = translator.translate(word)
            if result:
                return result
        except Exception as e:
            logger.warning(
                "Failed '%s' (attempt %d/%d): %s", word, attempt + 1, RETRY_ATTEMPTS, e
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return None


def main() -> None:
    import sys

    input_path = Path(sys.argv[1].strip())
    output_path = input_path.with_suffix(".json")
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path.name)
        return
    try:
        with input_path.open(encoding="utf-8") as f:
            words = [w.strip() for w in f if w.strip()]
    except Exception as e:
        logger.error("Error reading input file: %s", e)
        return
    if not words:
        print("No words found in %s", input_path.name)
        return
    print(
        "Loaded %d Persian words. Starting translation with %d workers...",
        len(words),
        MAX_WORKERS,
    )
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_word = {executor.submit(translate_word, word): word for word in words}
        for future in as_completed(future_to_word):
            persian_word = future_to_word[future]
            try:
                english_word = future.result()
                if english_word:
                    results[persian_word] = english_word
                    print(f"{persian_word} → {english_word}")
                else:
                    logger.error("Could not translate: %s", persian_word)
            except Exception as e:
                logger.error("Unexpected error for '%s': %s", persian_word, e)
    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(
            "Translation dictionary saved to %s (%d entries)",
            output_path.name,
            len(results),
        )
    except Exception as e:
        logger.error("Error saving results: %s", e)


if __name__ == "__main__":
    raise SystemExit(main())
