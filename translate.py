#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_WORKERS: Final[int] = 8
RETRY_ATTEMPTS: Final[int] = 4
RETRY_DELAY: Final[float] = 0.6
MAX_CHUNK_SIZE: Final[int] = 2000
SAVE_INTERVAL: Final[int] = 10
CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(
    r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1C80-\u1C8F]"
)

# ---------------------------------------------------------------------------
# Global interrupt flag (set by signal handlers)
# ---------------------------------------------------------------------------
interrupted: bool = False


def signal_handler(signum: int, frame: Any) -> None:
    """Mark the process as interrupted so loops can exit gracefully."""
    global interrupted
    interrupted = True
    logger.warning(
        "Received interrupt signal (Ctrl+C). Saving progress and exiting gracefully..."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def contains_cyrillic(text: str) -> bool:
    """Return True if `text` contains at least one Cyrillic character."""
    return bool(CYRILLIC_RE.search(text))


def create_chunks(lines: list[str], max_chunk_size: int) -> list[list[str]]:
    """Split `lines` into groups whose joined length stays below `max_chunk_size`."""
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_size: int = 0

    for line in lines:
        # +1 accounts for the newline separator that will be added when joining.
        line_size = len(line) + 1

        # A single oversized line becomes its own chunk.
        if line_size > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            chunks.append([line])
            continue

        if current_size + line_size > max_chunk_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(line)
        current_size += line_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# ---------------------------------------------------------------------------
# Worker: translate a single chunk (runs in a separate process)
# ---------------------------------------------------------------------------
def translate_chunk(
    chunk: list[str],
    source_lang: str,
    target_lang: str,
) -> tuple[list[str], str | None]:
    """
    Translate a whole chunk as a single request.

    Returns a tuple of (original_chunk, translated_text_or_None).
    `translated_text` is None when all retries failed.
    """
    if interrupted:
        return (chunk, None)

    chunk_text = "\n".join(chunk)
    translator = GoogleTranslator(source=source_lang, target=target_lang)

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        if interrupted:
            return (chunk, None)
        try:
            translated = translator.translate(chunk_text)
            if translated is not None:
                return (chunk, translated)
        except Exception as e:
            if interrupted:
                return (chunk, None)

            # Exponential backoff with a small jitter.
            delay = RETRY_DELAY * (2 ** (attempt - 1))
            jitter = random.uniform(0, delay * 0.25)
            sleep_time = delay + jitter

            logger.warning(
                "Translate attempt {}/{} failed for chunk starting '{}...': {}. Retrying in {:.2f}s",
                attempt,
                RETRY_ATTEMPTS,
                (chunk[0][:60] + "...") if chunk else "",
                e,
                sleep_time,
            )

            if attempt < RETRY_ATTEMPTS:
                time.sleep(sleep_time)

    return (chunk, None)


# ---------------------------------------------------------------------------
# Progress saving
# ---------------------------------------------------------------------------
def save_progress(
    all_lines: list[str],
    results: dict[str, str],
    output_path: Path,
    json_path: Path,
    source_lang: str,
    target_lang: str,
) -> None:
    """Write the current `results` mapping to both a text file and a JSON file."""
    try:
        # Plain text output (translated line if available, otherwise original).
        with output_path.open("w", encoding="utf-8") as f:
            translated_count = 0
            for line in all_lines:
                if line in results:
                    f.write(f"{results[line]}\n")
                    translated_count += 1
                else:
                    f.write(f"{line}\n")

        # Structured JSON output.
        json_data = {
            "metadata": {
                "source_lang": source_lang,
                "target_lang": target_lang,
                "total_lines": len(all_lines),
                "translated_lines": translated_count,
                "untranslated_lines": len(all_lines) - translated_count,
                "interrupted": interrupted,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "translations": {line: results.get(line, line) for line in all_lines},
        }

        with json_path.open("w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        print(
            f"Progress saved: {translated_count}/{len(all_lines)} lines translated "
            f"(Output: {output_path.name}, JSON: {json_path.name})"
        )
    except Exception as e:
        logger.error("Error saving progress: {}", e)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    global interrupted

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(
        description="Translate lines in a text file with progress saving."
    )
    parser.add_argument("-i", "--input", help="Input text file (one phrase per line)")
    parser.add_argument(
        "-s", "--source", default="ru", help="Source language code (default: ru)"
    )
    parser.add_argument(
        "-t", "--target", default="en", help="Target language code (default: en)"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Max worker processes (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--max-chunk-size",
        type=int,
        default=MAX_CHUNK_SIZE,
        help=f"Max characters per chunk (default: {MAX_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--save-interval",
        type=int,
        default=SAVE_INTERVAL,
        help=f"Save progress interval in seconds (default: {SAVE_INTERVAL})",
    )
    args = parser.parse_args()

    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        return

    # ------------------------------------------------------------------
    # Read input
    # ------------------------------------------------------------------
    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.rstrip("\n") for w in f if w.strip() != ""]
    except Exception as e:
        logger.error("Error reading input file: {}", e)
        return

    if not all_lines:
        print(f"No non-empty lines found in {input_path.name}")
        return

    source_lang = args.source
    target_lang = args.target

    # ------------------------------------------------------------------
    # Filter lines that actually need translation
    # ------------------------------------------------------------------
    if source_lang.lower().startswith("ru"):
        to_translate_raw = [line for line in all_lines if contains_cyrillic(line)]
        skipped_lines = [line for line in all_lines if not contains_cyrillic(line)]
    else:
        to_translate_raw = list(all_lines)
        skipped_lines = []

    print(
        f"Loaded {len(all_lines)} lines: "
        f"{len(to_translate_raw)} flagged for translation, {len(skipped_lines)} skipped"
    )

    if not to_translate_raw:
        print(f"No lines to translate for source_lang={source_lang}")
        return

    # ------------------------------------------------------------------
    # Deduplicate
    # ------------------------------------------------------------------
    seen: set[str] = set()
    to_translate_unique: list[str] = []
    for line in to_translate_raw:
        if line not in seen:
            seen.add(line)
            to_translate_unique.append(line)

    print(
        f"Deduplicated: {len(to_translate_unique)} unique lines to translate "
        f"(from {len(to_translate_raw)} total flagged)"
    )

    # Results maps an *original* line to its translation.
    results: dict[str, str] = {}

    output_path = input_path.with_name(
        f"{input_path.stem}_{target_lang}{input_path.suffix}"
    )
    json_path = input_path.with_name(f"{input_path.stem}_{target_lang}.json")

    # Initial save (all lines as-is, since nothing has been translated yet).
    save_progress(all_lines, results, output_path, json_path, source_lang, target_lang)

    if not interrupted:
        # --------------------------------------------------------------
        # Chunking & worker pool setup
        # --------------------------------------------------------------
        chunks = create_chunks(to_translate_unique, args.max_chunk_size)
        num_workers = min(max(1, args.max_workers), len(chunks))
        print(
            f"Created {len(chunks)} chunk(s) from {len(to_translate_unique)} remaining lines "
            f"(max {args.max_chunk_size} chars per chunk), using {num_workers} worker(s)"
        )

        # Background thread periodically persists progress.
        last_save_time = time.time()
        save_lock = threading.Lock()

        def periodic_save() -> None:
            nonlocal last_save_time
            while not interrupted:
                time.sleep(args.save_interval)
                if not interrupted:
                    with save_lock:
                        save_progress(
                            all_lines,
                            results,
                            output_path,
                            json_path,
                            source_lang,
                            target_lang,
                        )
                        last_save_time = time.time()

        save_thread = threading.Thread(target=periodic_save, daemon=True)
        save_thread.start()

        try:
            with mp.Pool(processes=num_workers) as pool:
                # Submit every chunk asynchronously via apply_async.
                async_results = [
                    (
                        pool.apply_async(
                            translate_chunk,
                            (chunk, source_lang, target_lang),
                        ),
                        chunk,
                    )
                    for chunk in chunks
                ]

                completed = 0
                total = len(async_results)

                for async_result, chunk in async_results:
                    if interrupted:
                        print("Interrupted. Waiting for running tasks to complete...")
                        pool.terminate()
                        break

                    completed += 1

                    try:
                        original_lines, translated_text = async_result.get()

                        if translated_text and not interrupted:
                            translated_lines = translated_text.splitlines()

                            if len(translated_lines) == len(original_lines):
                                # Happy path: line counts match.
                                for i, original_line in enumerate(original_lines):
                                    tgt = translated_lines[i]
                                    results[original_line] = tgt
                            else:
                                # Fallback: translate line by line.
                                logger.warning(
                                    "Line-count mismatch in chunk ({} original vs {} translated). "
                                    "Falling back to per-line translation for this chunk.",
                                    len(original_lines),
                                    len(translated_lines),
                                )
                                for line in original_lines:
                                    if interrupted:
                                        break
                                    try:
                                        per_line_translator = GoogleTranslator(
                                            source=source_lang, target=target_lang
                                        )
                                        t = per_line_translator.translate(line)
                                        if t is None:
                                            t = line
                                        results[line] = t
                                    except Exception as e:
                                        logger.error(
                                            "Per-line fallback failed for '{}': {}",
                                            line[:50],
                                            e,
                                        )
                                        results[line] = line

                            print(
                                f"Translated chunk {completed}/{total} "
                                f"(sample: '{original_lines[0][:40]}"
                                f"{'...' if len(original_lines[0]) > 40 else ''}' -> "
                                f"'{results.get(original_lines[0], '')[:60]}')"
                            )
                        else:
                            if not interrupted:
                                logger.error(
                                    "Failed to translate chunk starting with: {}",
                                    (chunk[0][:60] + "...") if chunk else "",
                                )
                                for line in chunk:
                                    try:
                                        t = GoogleTranslator(
                                            source=source_lang, target=target_lang
                                        ).translate(line)
                                        if t is None:
                                            t = line
                                        results[line] = t
                                    except Exception as e:
                                        logger.error(
                                            "Per-line retry failed for '{}': {}",
                                            line[:50],
                                            e,
                                        )
                                        results[line] = line

                    except Exception as e:
                        if not interrupted:
                            logger.error(
                                "Unexpected error processing chunk starting with '{}': {}",
                                (chunk[0][:60] + "...") if chunk else "",
                                e,
                            )

                    # Time-based save (backup for the periodic saver).
                    if time.time() - last_save_time >= args.save_interval:
                        with save_lock:
                            save_progress(
                                all_lines,
                                results,
                                output_path,
                                json_path,
                                source_lang,
                                target_lang,
                            )
                            last_save_time = time.time()

        except KeyboardInterrupt:
            logger.warning("Keyboard interrupt detected. Saving progress...")
            interrupted = True
        except Exception as e:
            logger.error("Unexpected error: {}", e)

    # Final save
    save_progress(all_lines, results, output_path, json_path, source_lang, target_lang)

    if interrupted:
        logger.warning("Process was interrupted. Progress has been saved.")
        print("You can resume by running the command again.")
    else:
        translated_count = sum(
            1 for line in all_lines if line in results and results[line] != line
        )
        print(
            f"Translation complete: {translated_count}/{len(all_lines)} lines translated successfully"
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user. Exiting...")
        sys.exit(1)
