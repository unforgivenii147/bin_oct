#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Persian (Farsi) lines in a text file to English and save results.

Prompt: Write a Python 3 script that reads a UTF-8 text file from argv[1],
detects lines containing Persian characters, translates them to English using
deep_translator.GoogleTranslator in chunks (max 2000 chars) via
multiprocessing.Pool.apply_async with a fixed pool of 8 workers and up to 3
retries per chunk, then writes a JSON mapping of original→translated lines to
<name>.json and rewrites the input file with translations in place (untranslated
lines left unchanged). Use loguru for logging, pathlib for paths, and complete
strict type annotations throughout.
"""

from __future__ import annotations

import json
import re
import sys
import time
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from loguru import logger

MAX_WORKERS: Final[int] = 8
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5
MAX_CHUNK_SIZE: Final[int] = 2000

PERSIAN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def contains_persian(text: str) -> bool:
    """Return True if the given text contains at least one Persian character."""
    return bool(PERSIAN_PATTERN.search(text))


def create_chunks(lines: list[str]) -> list[list[str]]:
    """Group lines into chunks whose total joined length stays under MAX_CHUNK_SIZE."""
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_size: int = 0

    for line in lines:
        line_size: int = len(line) + 1

        if current_size + line_size > MAX_CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        if line_size > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            chunks.append([line])
        else:
            current_chunk.append(line)
            current_size += line_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def translate_chunk(chunk: list[str]) -> tuple[list[str], str | None]:
    """Translate a chunk of Persian lines to English, retrying up to RETRY_ATTEMPTS times."""
    chunk_text: str = "\n".join(chunk)
    translator: GoogleTranslator = GoogleTranslator(source="fa", target="en")

    for attempt in range(RETRY_ATTEMPTS):
        try:
            result: str | None = translator.translate(chunk_text)
            if result:
                return (chunk, result)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed chunk starting with '{}' (attempt {}/{}): {}",
                chunk[0][:50],
                attempt + 1,
                RETRY_ATTEMPTS,
                e,
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)

    return (chunk, None)


def read_lines(input_path: Path) -> list[str]:
    """Read a UTF-8 file and return a list of stripped non-empty lines."""
    with input_path.open(encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_json(results: dict[str, str], output_path: Path) -> None:
    """Write the translation mapping to a UTF-8 JSON file."""
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def rewrite_input(
    input_path: Path, all_lines: list[str], results: dict[str, str]
) -> None:
    """Rewrite the input file, replacing translated lines with their English versions."""
    with input_path.open("w", encoding="utf-8") as f:
        for line in all_lines:
            f.write(f"{results.get(line, line)}\n")


def collect_results(chunks: list[list[str]], pool: Pool) -> dict[str, str]:
    """Dispatch chunks to the pool and collect original→translated line mappings."""
    results: dict[str, str] = {}
    async_results: list[AsyncResult[tuple[list[str], str | None]]] = [
        pool.apply_async(translate_chunk, (chunk,)) for chunk in chunks
    ]

    for async_result in async_results:
        try:
            original_lines, translated_text = async_result.get()
        except Exception as e:  # noqa: BLE001
            logger.error("Unexpected error while translating chunk: {}", e)
            continue

        if not translated_text:
            logger.error(
                "Failed to translate chunk starting with: {}", original_lines[0][:50]
            )
            continue

        translated_lines: list[str] = translated_text.split("\n")
        for i, original_line in enumerate(original_lines):
            if i < len(translated_lines):
                results[original_line] = translated_lines[i]
                print("{} → {}", original_line, translated_lines[i])
            else:
                logger.error(
                    "Line count mismatch in chunk, missing translation for: {}",
                    original_line,
                )

    return results


def main() -> int:
    """Entry point: read input file, translate Persian lines, and persist results."""
    if len(sys.argv) < 2:
        logger.error("Usage: {} <input_file>", sys.argv[0])
        return 1

    input_path: Path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path.name)
        return 1

    try:
        all_lines: list[str] = read_lines(input_path)
    except Exception as e:  # noqa: BLE001
        logger.error("Error reading input file: {}", e)
        return 1

    if not all_lines:
        print("No lines found in {}", input_path.name)
        return 0

    persian_lines: list[str] = [line for line in all_lines if contains_persian(line)]
    non_persian_count: int = len(all_lines) - len(persian_lines)

    print(
        "Loaded {} lines: {} with persian, {} already English/skipped",
        len(all_lines),
        len(persian_lines),
        non_persian_count,
    )

    if not persian_lines:
        print("No persian lines to translate in {}", input_path.name)
        return 0

    chunks: list[list[str]] = create_chunks(persian_lines)
    print(
        "Created {} chunks from {} persian lines (max {} chars per chunk)",
        len(chunks),
        len(persian_lines),
        MAX_CHUNK_SIZE,
    )

    results: dict[str, str] = {}
    pool: Pool = Pool(processes=MAX_WORKERS)
    try:
        results = collect_results(chunks, pool)
    finally:
        pool.close()
        pool.join()

    output_path: Path = input_path.with_suffix(".json")
    try:
        save_json(results, output_path)
        print("Saved {} translations to {}", len(results), output_path.name)
    except Exception as e:  # noqa: BLE001
        logger.error("Error saving JSON file: {}", e)

    try:
        rewrite_input(input_path, all_lines, results)
        print(
            "Updated {}: translated {} lines, kept {} lines unchanged",
            input_path.name,
            len(results),
            non_persian_count,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Error updating input file: {}", e)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
