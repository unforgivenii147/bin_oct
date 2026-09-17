#!/data/data/com.termux/files/home/.local/bin/python
"""Translate a text file of Persian words to English with GoogleTranslator, a multiprocessing pool of 8 workers, loguru logging, and save a JSON dictionary."""

import json
import sys
import time
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5


def translate_word(word: str) -> tuple[str, str | None]:
    """Translate one word to English, returning the original word and translation or None."""
    translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")

    for attempt in range(RETRY_ATTEMPTS):
        try:
            result: str | None = translator.translate(word)
            if result:
                return word, result
        except Exception as e:
            logger.warning(
                "Failed '{}' (attempt {}/{}): {}",
                word,
                attempt + 1,
                RETRY_ATTEMPTS,
                e,
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)

    return word, None


def main() -> None:
    """Read words from a file, translate them in parallel, and save a JSON dictionary."""
    if len(sys.argv) < 2:
        logger.error("Usage: {} <input_file>", Path(sys.argv[0]).name)
        return

    input_path: Path = Path(sys.argv[1].strip())
    output_path: Path = input_path.with_suffix(".json")

    if not input_path.exists():
        logger.error("Input file not found: {}", input_path.name)
        return

    try:
        with input_path.open(encoding="utf-8") as f:
            words: list[str] = [w.strip() for w in f if w.strip()]
    except Exception as e:
        logger.error("Error reading input file: {}", e)
        return

    if not words:
        logger.info("No words found in {}", input_path.name)
        return

    logger.info(
        "Loaded {} Persian words. Starting translation with {} workers...",
        len(words),
        MAX_WORKERS,
    )

    results: dict[str, str] = {}

    with Pool(processes=MAX_WORKERS) as pool:
        for persian_word, english_word in pool.imap_unordered(translate_word, words):
            if english_word:
                results[persian_word] = english_word
                logger.info("{} → {}", persian_word, english_word)
            else:
                logger.error("Could not translate: {}", persian_word)

    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logger.info(
            "Translation dictionary saved to {} ({} entries)",
            output_path.name,
            len(results),
        )
    except Exception as e:
        logger.error("Error saving results: {}", e)


if __name__ == "__main__":
    raise SystemExit(main())
