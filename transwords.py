#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Persian text in ``words.txt`` into English, chunk by chunk, and write
the results to ``fa_en.json``. Text is split into ``CHUNK_SIZE``-character
line-ranges, each chunk is translated via deep-translator's GoogleTranslator in
a fixed multiprocessing.Pool of 8 workers, and the successful translations are
sorted by starting line before serialization. Logging via loguru.
"""

import json
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final, TypedDict

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 8
INPUT_FILE: Final[Path] = Path("words.txt")
OUTPUT_FILE: Final[Path] = Path("fa_en.json")


class TranslationResult(TypedDict):
    """A single translated chunk of source text."""

    chunk_id: str
    start_line: int
    end_line: int
    original: str
    translated: str


Chunk = tuple[int, int, str]


def chunk_file(file_path: Path, chunk_size: int = CHUNK_SIZE) -> list[Chunk]:
    """
    Split ``file_path`` into chunks of at most ``chunk_size`` characters,
    preserving line boundaries.

    Args:
        file_path: Source text file to read.
        chunk_size: Maximum character count per chunk.

    Returns:
        A list of ``(start_line, end_line, text)`` tuples. Empty on read error.
    """
    chunks: list[Chunk] = []
    current_chunk: list[str] = []
    current_size: int = 0
    start_line: int = 0
    line_num: int = 0

    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f):
                if current_size + len(line) > chunk_size and current_chunk:
                    chunks.append((start_line, line_num - 1, "".join(current_chunk)))
                    current_chunk = [line]
                    current_size = len(line)
                    start_line = line_num
                else:
                    current_chunk.append(line)
                    current_size += len(line)
            if current_chunk:
                chunks.append((start_line, line_num, "".join(current_chunk)))
    except Exception as exc:
        logger.error(f"Error reading file {file_path}: {exc}")

    return chunks


def translate_chunk(
    chunk_data: Chunk, chunk_index: int, total_chunks: int
) -> TranslationResult | None:
    """
    Translate a single chunk of Persian text into English.

    Pauses briefly before translating any chunk after the first to avoid
    hammering the upstream translation service.

    Args:
        chunk_data: ``(start_line, end_line, text)`` tuple to translate.
        chunk_index: Zero-based index of this chunk (used for throttling).
        total_chunks: Total number of chunks being processed (for logging).

    Returns:
        A :class:`TranslationResult`, or ``None`` if translation failed or
        produced an empty result.
    """
    start_line, end_line, text = chunk_data

    if chunk_index > 0:
        time.sleep(2)

    try:
        translator: GoogleTranslator = GoogleTranslator(source="fa", target="en")
        translated: str | None = translator.translate(text)
        if not translated:
            return None
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "original": text,
            "translated": translated,
        }
    except Exception as exc:
        logger.error(f"Error translating chunk {start_line}_{end_line}: {exc}")
        return None


def main() -> None:
    """Read, translate, and persist the chunked translation results."""
    if not INPUT_FILE.exists():
        logger.error(f"Input file {INPUT_FILE} not found.")
        return

    print("Extracting chunks...")
    chunks: list[Chunk] = chunk_file(INPUT_FILE)
    print(f"Total chunks: {len(chunks)}")

    if not chunks:
        logger.warning("No text found to translate.")
        return

    print("Translating chunks...")
    translations: list[TranslationResult] = []
    total_chunks: int = len(chunks)

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[TranslationResult | None]] = [
            pool.apply_async(translate_chunk, (chunk, idx, total_chunks))
            for idx, chunk in enumerate(chunks)
        ]

        for i, async_res in enumerate(async_results, 1):
            result: TranslationResult | None = async_res.get()
            if result is not None:
                translations.append(result)
            print(f"Progress: {i}/{total_chunks}")

    if not translations:
        logger.warning("No translations were successful.")
        return

    print(f"Writing results to {OUTPUT_FILE}...")
    try:
        final_data: dict[str, list[TranslationResult]] = {
            "translations": sorted(translations, key=lambda item: item["start_line"])
        }
        OUTPUT_FILE.write_text(
            json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Done!")
    except Exception as exc:
        logger.error(f"Error writing output file: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
