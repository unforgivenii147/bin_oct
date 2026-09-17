#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Chinese lines in a UTF-8 text file to English in place, keeping all
other lines unchanged. Reads the input path from ``sys.argv[1]``, filters lines
that contain CJK characters, translates them via deep-translator's
GoogleTranslator with retries, and rewrites the file preserving the original
line order. Uses a fixed multiprocessing.Pool of 8 workers; logging via loguru.
"""

import re
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5
CHINESE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]"
)

TranslateResult = tuple[str, str | None]


def contains_chinese(text: str) -> bool:
    """
    Return whether ``text`` contains any CJK/CJK-compatibility character.

    Args:
        text: The text to inspect.

    Returns:
        ``True`` if a Chinese character is present, ``False`` otherwise.
    """
    return bool(CHINESE_PATTERN.search(text))


def translate_line(line: str) -> TranslateResult:
    """
    Translate a single line from an auto-detected source language to English.

    Retries up to :data:`RETRY_ATTEMPTS` times, pausing :data:`RETRY_DELAY`
    seconds between attempts.

    Args:
        line: The source line to translate.

    Returns:
        A tuple ``(line, translated)`` where ``translated`` is the English text
        on success, or ``None`` if every attempt failed.
    """
    translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result: str | None = translator.translate(line)
            if result:
                return line, result
        except Exception as exc:
            logger.warning(
                f"Failed '{line}' (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {exc}"
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return line, None


def main() -> None:
    """Translate Chinese lines in the file named by ``sys.argv[1]`` in place."""
    if len(sys.argv) < 2:
        logger.error("Usage: script.py INPUT_FILE")
        sys.exit(1)

    input_path: Path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path.name}")
        return

    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines: list[str] = [w.strip() for w in f if w.strip()]
    except Exception as exc:
        logger.error(f"Error reading input file: {exc}")
        return

    if not all_lines:
        print(f"No lines found in {input_path.name}")
        return

    chinese_lines: list[str] = [line for line in all_lines if contains_chinese(line)]
    non_chinese_lines: list[str] = [
        line for line in all_lines if not contains_chinese(line)
    ]

    print(
        f"Loaded {len(all_lines)} lines: {len(chinese_lines)} with Chinese, "
        f"{len(non_chinese_lines)} already English/skipped"
    )

    if not chinese_lines:
        print(f"No Chinese lines to translate in {input_path.name}")
        return

    print(f"Starting translation with {MAX_WORKERS} workers...")

    results: dict[str, str] = {}

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[TranslateResult]] = [
            pool.apply_async(translate_line, (line,)) for line in chinese_lines
        ]
        for chinese_line, async_res in zip(chinese_lines, async_results):
            try:
                _, english_line = async_res.get()
                if english_line:
                    results[chinese_line] = english_line
                    print(f"{chinese_line} → {english_line}")
                else:
                    logger.error(f"Could not translate: {chinese_line}")
            except Exception as exc:
                logger.error(f"Unexpected error for '{chinese_line}': {exc}")

    try:
        with input_path.open("w", encoding="utf-8") as f:
            for line in all_lines:
                if line in results:
                    f.write(f"{results[line]}\n")
                else:
                    f.write(f"{line}\n")
        print(
            f"Updated {input_path.name}: translated {len(results)} lines, "
            f"kept {len(non_chinese_lines)} lines unchanged"
        )
    except Exception as exc:
        logger.error(f"Error updating input file: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
