#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Persian words from a text file to English using Google Translate.

Reads words from ``words.txt`` (one per line), translates each unique word
concurrently using a multiprocessing pool of 8 workers, and stores results
incrementally in ``dic.json`` as a mapping of Persian word to English
translation. Existing translations are preserved and skipped, progress is
saved atomically every 1000 new entries, and Ctrl-C triggers a final save.
"""

from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path
from typing import Any

from deep_translator import GoogleTranslator
from loguru import logger
from tqdm import tqdm

INPUT_FILE: str = "words.txt"
OUTPUT_FILE: str = "dic.json"
MAX_WORKERS: int = 8
SAVE_EVERY: int = 1000
MAX_RETRIES: int = 3
RETRY_DELAY_SECONDS: float = 0.5


def translate_word(word: str) -> str | None:
    """Translate a single word to English, retrying on failure.

    Args:
        word: The source word to translate.

    Returns:
        The translated English string, or ``None`` if all retries failed.
    """
    for attempt in range(MAX_RETRIES):
        try:
            return GoogleTranslator(source="auto", target="en").translate(word)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed '{}' (attempt {}/{}): {}",
                word,
                attempt + 1,
                MAX_RETRIES,
                exc,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    return None


def load_words(input_file: str) -> list[str]:
    """Load non-empty, stripped lines from a text file.

    Args:
        input_file: Path to the file containing one word per line.

    Returns:
        A list of unique, non-empty words preserving input order.
    """
    seen: set[str] = set()
    words: list[str] = []
    with Path(input_file).open(encoding="utf-8") as fh:
        for raw in fh:
            word = raw.strip()
            if word and word not in seen:
                seen.add(word)
                words.append(word)
    return words


def load_existing_results(output_file: str) -> dict[str, str]:
    """Load previously saved translations from a JSON file.

    Args:
        output_file: Path to the JSON dictionary file.

    Returns:
        A mapping of source words to translations. Empty if the file is
        missing or malformed.
    """
    path = Path(output_file)
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data: Any = json.load(fh)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        logger.warning("Existing {} is not a JSON object; ignoring.", output_file)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load existing {}: {}", output_file, exc)
    return {}


def save_results_atomic(results: dict[str, str], output_file: str) -> None:
    """Atomically write the translation dictionary to disk.

    Writes to a temporary file first, then replaces the target file to
    avoid corrupting the output on interruption.

    Args:
        results: Mapping of source words to translations.
        output_file: Destination JSON path.
    """
    target = Path(output_file)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    tmp.replace(target)


def main() -> int:
    """Run the translation pipeline.

    Returns:
        Process exit code (0 on success).
    """
    words = load_words(INPUT_FILE)
    print("Loaded {} Persian words", len(words))

    results = load_existing_results(OUTPUT_FILE)
    print("Loaded {} existing translations from {}", len(results), OUTPUT_FILE)

    to_translate = [w for w in words if w not in results]
    total_remaining = len(to_translate)
    print("{} words to translate (skipping already translated)", total_remaining)

    if total_remaining == 0:
        print("Nothing to do. Exiting.")
        return 0

    new_count = 0
    pbar = tqdm(total=total_remaining, desc="Translating", unit="word")

    # Shared counter used by worker callbacks; multiprocessing-safe via Value.
    counter = multiprocessing.Value("i", 0)

    def on_success(word: str, translation: str | None) -> None:
        """Handle a completed translation task.

        Args:
            word: The source word.
            translation: The translated text, or ``None`` on failure.
        """
        nonlocal new_count
        if translation:
            results[word] = translation
            new_count += 1
            print("{} → {}", word, translation)
        else:
            logger.error("Could not translate: {}", word)
        pbar.update(1)
        with counter.get_lock():
            counter.value += 1
            current = counter.value
        if current % SAVE_EVERY == 0:
            print("Saving progress after {} new translations...", new_count)
            save_results_atomic(results, OUTPUT_FILE)

    def on_error(exc: BaseException) -> None:
        """Handle an unexpected worker failure.

        Args:
            exc: The exception raised by the worker.
        """
        logger.error("Unexpected worker error: {}", exc)
        pbar.update(1)

    try:
        with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
            for word in to_translate:
                pool.apply_async(
                    translate_word,
                    args=(word,),
                    callback=lambda translation, w=word: on_success(w, translation),
                    error_callback=on_error,
                )
            pool.close()
            pool.join()
    except KeyboardInterrupt:
        print("Interrupted by user. Saving progress...")
    finally:
        save_results_atomic(results, OUTPUT_FILE)
        pbar.close()
        print("Translation dictionary saved to {}", OUTPUT_FILE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
