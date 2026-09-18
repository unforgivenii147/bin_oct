#!/data/data/com.termux/files/home/.local/bin/python
# --- File: fa_translate.py ---
"""
Merged Persian/English translation tool.

This single script combines the behavior of:
  - fa_trans.py      -> `lines` subcommand
  - tfa.py           -> `words` subcommand with --processes 1 and --output dic.json
  - trans_fa_mp.py   -> `words` subcommand with --processes 8

Dependencies (third-party):
    pip install deep-translator loguru

Usage examples:
    python fa_translate.py lines input.txt
    python fa_translate.py words words.txt --output dic.json --processes 1
    python fa_translate.py words input.txt --processes 8

Original-to-merged mapping:
    fa_trans.py      -> python fa_translate.py lines <input_file>
    tfa.py           -> python fa_translate.py words words.txt --output dic.json --processes 1
    trans_fa_mp.py   -> python fa_translate.py words <input_file> --processes 8
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final, Sequence

from deep_translator import GoogleTranslator
from loguru import logger

# Persian/Arabic script ranges used by fa_trans.py to decide which lines need translation.
PERSIAN_RE: Final = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def contains_persian(text: str) -> bool:
    """Return True if *text* contains at least one Persian/Arabic character."""
    return bool(PERSIAN_RE.search(text))


def read_nonempty_lines(path: Path) -> list[str]:
    """Read a UTF-8 text file, strip each line, and drop empty lines."""
    with path.open(encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def write_json(path: Path, data: dict[str, str]) -> None:
    """Write a UTF-8 JSON dictionary with indentation, preserving non-ASCII text."""
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def rewrite_lines(
    path: Path, original_lines: Sequence[str], translations: dict[str, str]
) -> None:
    """Rewrite *path* replacing each original line with its translation when available."""
    with path.open("w", encoding="utf-8") as file:
        for line in original_lines:
            file.write(f"{translations.get(line, line)}\n")


def chunk_lines(lines: Sequence[str], max_chars: int) -> list[list[str]]:
    """
    Group lines into chunks whose joined length is at most *max_chars*.

    This mirrors fa_trans.py: each line contributes len(line) + 1, and a single
    line longer than max_chars becomes its own chunk.
    """
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_length = 0

    for line in lines:
        line_length = len(line) + 1

        if current_length + line_length > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_length = 0

        if line_length > max_chars:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_length = 0
            chunks.append([line])
        else:
            current_chunk.append(line)
            current_length += line_length

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def translate_with_retry(
    text: str,
    source: str,
    target: str,
    retries: int,
    retry_delay: float,
    context: str = "text",
) -> str | None:
    """
    Translate *text* with GoogleTranslator, retrying on exceptions.

    Returns the translated string, or None if all attempts fail or produce empty output.
    """
    translator = GoogleTranslator(source=source, target=target)

    for attempt in range(retries):
        try:
            result = translator.translate(text)
            if result:
                return result
        except Exception as exc:
            logger.warning(
                "Failed {} '{}' (attempt {}/{}): {}",
                context,
                text[:50].replace("\n", " "),
                attempt + 1,
                retries,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(retry_delay)

    return None


def _translate_chunk_worker(
    args: tuple[list[str], str, str, int, float],
) -> tuple[list[str], str | None]:
    """Multiprocessing worker: translate one newline-joined chunk of lines."""
    lines, source, target, retries, retry_delay = args
    text = "\n".join(lines)
    translated = translate_with_retry(
        text,
        source=source,
        target=target,
        retries=retries,
        retry_delay=retry_delay,
        context="chunk starting with",
    )
    return lines, translated


def _translate_word_worker(
    args: tuple[str, str, str, int, float],
) -> tuple[str, str | None]:
    """Multiprocessing worker: translate one word/phrase."""
    word, source, target, retries, retry_delay = args
    translated = translate_with_retry(
        word,
        source=source,
        target=target,
        retries=retries,
        retry_delay=retry_delay,
        context="word",
    )
    return word, translated


def translate_chunks(
    chunks: Sequence[Sequence[str]],
    source: str,
    target: str,
    processes: int,
    retries: int,
    retry_delay: float,
) -> dict[str, str]:
    """
    Translate chunks in parallel and build a mapping original-line -> translated-line.

    This reproduces fa_trans.py's chunk mapping behavior, including line-count
    mismatch warnings.
    """
    translations: dict[str, str] = {}

    pool = Pool(processes=processes)
    try:
        async_results = [
            pool.apply_async(
                _translate_chunk_worker,
                ((list(chunk), source, target, retries, retry_delay),),
            )
            for chunk in chunks
        ]

        for async_result in async_results:
            try:
                original_lines, translated = async_result.get()
            except Exception as exc:
                logger.error("Unexpected error while translating chunk: {}", exc)
                continue

            if not translated:
                logger.error(
                    "Failed to translate chunk starting with: {}",
                    original_lines[0][:50],
                )
                continue

            translated_lines = translated.split("\n")

            for index, original_line in enumerate(original_lines):
                if index < len(translated_lines):
                    translations[original_line] = translated_lines[index]
                    logger.info("{} → {}", original_line, translated_lines[index])
                else:
                    logger.error(
                        "Line count mismatch in chunk, missing translation for: {}",
                        original_line,
                    )
    finally:
        pool.close()
        pool.join()

    return translations


def translate_words(
    words: Sequence[str],
    source: str,
    target: str,
    processes: int,
    retries: int,
    retry_delay: float,
) -> dict[str, str]:
    """
    Translate words/phrases and return a mapping original-word -> translation.

    If processes <= 1, this behaves like tfa.py: sequential translation.
    Otherwise, it behaves like trans_fa_mp.py: multiprocessing with imap_unordered.
    """
    translations: dict[str, str] = {}

    if processes <= 1:
        for word in words:
            _, translated = _translate_word_worker(
                (word, source, target, retries, retry_delay)
            )
            if translated:
                translations[word] = translated
                logger.info("{} → {}", word, translated)
            else:
                logger.error("Could not translate: {}", word)
        return translations

    with Pool(processes=processes) as pool:
        args_iter = ((word, source, target, retries, retry_delay) for word in words)
        for word, translated in pool.imap_unordered(_translate_word_worker, args_iter):
            if translated:
                translations[word] = translated
                logger.info("{} → {}", word, translated)
            else:
                logger.error("Could not translate: {}", word)

    return translations


def cmd_lines(args: argparse.Namespace) -> int:
    """Handle the `lines` subcommand, equivalent to fa_trans.py."""
    input_path: Path = args.input_file

    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        return 1

    try:
        all_lines = read_nonempty_lines(input_path)
    except Exception as exc:
        logger.error("Error reading input file: {}", exc)
        return 1

    if not all_lines:
        logger.info("No lines found in {}", input_path.name)
        return 0

    persian_lines = [line for line in all_lines if contains_persian(line)]
    skipped_count = len(all_lines) - len(persian_lines)

    logger.info(
        "Loaded {} lines: {} with Persian, {} already English/skipped",
        len(all_lines),
        len(persian_lines),
        skipped_count,
    )

    if not persian_lines:
        logger.info("No Persian lines to translate in {}", input_path.name)
        return 0

    chunks = chunk_lines(persian_lines, args.max_chars)
    logger.info(
        "Created {} chunks from {} Persian lines (max {} chars per chunk)",
        len(chunks),
        len(persian_lines),
        args.max_chars,
    )

    translations = translate_chunks(
        chunks=chunks,
        source=args.source,
        target=args.target,
        processes=args.processes,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )

    json_path: Path = (
        args.json_out if args.json_out is not None else input_path.with_suffix(".json")
    )

    try:
        write_json(json_path, translations)
        logger.info("Saved {} translations to {}", len(translations), json_path.name)
    except Exception as exc:
        logger.error("Error saving JSON file: {}", exc)

    if args.update:
        try:
            rewrite_lines(input_path, all_lines, translations)
            logger.info(
                "Updated {}: translated {} lines, kept {} lines unchanged",
                input_path.name,
                len(translations),
                skipped_count,
            )
        except Exception as exc:
            logger.error("Error updating input file: {}", exc)
            return 1

    return 0


def cmd_words(args: argparse.Namespace) -> int:
    """Handle the `words` subcommand, equivalent to tfa.py or trans_fa_mp.py."""
    input_path: Path = args.input_file

    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        return 1

    try:
        words = read_nonempty_lines(input_path)
    except Exception as exc:
        logger.error("Error reading input file: {}", exc)
        return 1

    if not words:
        logger.info("No words found in {}", input_path.name)
        return 0

    logger.info(
        "Loaded {} Persian words. Starting translation with {} workers...",
        len(words),
        args.processes,
    )

    translations = translate_words(
        words=words,
        source=args.source,
        target=args.target,
        processes=args.processes,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )

    output_path: Path = (
        args.output if args.output is not None else input_path.with_suffix(".json")
    )

    try:
        write_json(output_path, translations)
        logger.info(
            "Translation dictionary saved to {} ({} entries)",
            output_path.name,
            len(translations),
        )
    except Exception as exc:
        logger.error("Error saving results: {}", exc)
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argparse CLI with `lines` and `words` subcommands."""
    parser = argparse.ArgumentParser(
        description=(
            "Translate Persian text/word lists to English. "
            "Merged from fa_trans.py, tfa.py, and trans_fa_mp.py."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    # ------------------------------------------------------------------
    # `lines` subcommand: fa_trans.py
    # ------------------------------------------------------------------
    lines_parser = subparsers.add_parser(
        "lines",
        help=(
            "Translate Persian lines in a text file, update the file in place, "
            "and write a JSON dictionary."
        ),
    )
    lines_parser.add_argument("input_file", type=Path, help="Input text file.")
    lines_parser.add_argument(
        "--source",
        default="fa",
        help="Source language (default: fa).",
    )
    lines_parser.add_argument(
        "--target",
        default="en",
        help="Target language (default: en).",
    )
    lines_parser.add_argument(
        "-p",
        "--processes",
        type=int,
        default=8,
        help="Worker processes (default: 8).",
    )
    lines_parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=3,
        help="Translation retries per chunk (default: 3).",
    )
    lines_parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5).",
    )
    lines_parser.add_argument(
        "--max-chars",
        type=int,
        default=2000,
        help="Max characters per chunk (default: 2000).",
    )
    lines_parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="JSON output path (default: <input>.json).",
    )
    lines_parser.add_argument(
        "--no-update",
        action="store_false",
        dest="update",
        default=True,
        help="Do not rewrite the input file; only write the JSON dictionary.",
    )
    lines_parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (default: INFO).",
    )
    lines_parser.set_defaults(func=cmd_lines)

    # ------------------------------------------------------------------
    # `words` subcommand: tfa.py and trans_fa_mp.py
    # ------------------------------------------------------------------
    words_parser = subparsers.add_parser(
        "words",
        help="Translate a word list to English and write a JSON dictionary.",
    )
    words_parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        default=Path("words.txt"),
        help="Input word list (default: words.txt).",
    )
    words_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="JSON output path (default: <input>.json).",
    )
    words_parser.add_argument(
        "--source",
        default="auto",
        help="Source language (default: auto).",
    )
    words_parser.add_argument(
        "--target",
        default="en",
        help="Target language (default: en).",
    )
    words_parser.add_argument(
        "-p",
        "--processes",
        type=int,
        default=8,
        help="Worker processes; use 1 for sequential behavior (default: 8).",
    )
    words_parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=3,
        help="Translation retries per word (default: 3).",
    )
    words_parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5).",
    )
    words_parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (default: INFO).",
    )
    words_parser.set_defaults(func=cmd_words)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, configure logging, and dispatch to the selected subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    logger.remove()
    logger.add(sys.stderr, level=getattr(args, "log_level", "INFO"))

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
