#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import json
import multiprocessing as mp
import os
import random
import re
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from loguru import logger

MAX_WORKERS: Final[int] = 8
RETRY_ATTEMPTS: Final[int] = 4
RETRY_DELAY: Final[float] = 0.6
MAX_CHUNK_SIZE: Final[int] = 2000
SAVE_INTERVAL: Final[int] = 10
CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(
    r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1C80-\u1C8F]"
)

# SQLite has a limit (usually 999) on the number of bound variables per statement.
# We use a conservative batch size so we never hit that limit.
SQLITE_BATCH_SIZE: Final[int] = 500

interrupted: bool = False


def signal_handler(signum: int, frame: Any) -> None:
    global interrupted
    interrupted = True
    logger.warning(
        "Received interrupt signal (Ctrl+C). Saving progress and exiting gracefully..."
    )


def contains_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text))


def create_chunks(lines: list[str], max_chunk_size: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_size: int = 0

    for line in lines:
        line_size = len(line) + 1
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


class TranslationCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path: Path = db_path.expanduser()
        parent: Path = Path(self.db_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY,
                source_text TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_text, source_lang, target_lang)
            )
            """)
        self.conn.commit()
        self.lock: threading.Lock = threading.Lock()

    def get_many(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> dict[str, str]:
        if not texts:
            return {}
        result: dict[str, str] = {}
        with self.lock:
            # Batch the queries so we never exceed SQLite's bound-variable limit.
            for i in range(0, len(texts), SQLITE_BATCH_SIZE):
                batch = texts[i : i + SQLITE_BATCH_SIZE]
                placeholders = ",".join(["?"] * len(batch))
                query = f"""
                    SELECT source_text, translated_text FROM translations
                    WHERE source_lang = ? AND target_lang = ?
                      AND source_text IN ({placeholders})
                """
                params = [source_lang, target_lang] + batch
                cur = self.conn.execute(query, params)
                for row in cur.fetchall():
                    result[row[0]] = row[1]
        return result

    def set_many(
        self, translations: dict[str, str], source_lang: str, target_lang: str
    ) -> None:
        if not translations:
            return
        with self.lock:
            data = [
                (src, source_lang, target_lang, tgt)
                for src, tgt in translations.items()
            ]
            # executemany does not build one giant statement, but we still
            # chunk it for safety / lower memory churn on huge dicts.
            for i in range(0, len(data), SQLITE_BATCH_SIZE):
                batch = data[i : i + SQLITE_BATCH_SIZE]
                self.conn.executemany(
                    """
                    INSERT INTO translations
                        (source_text, source_lang, target_lang, translated_text, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_text, source_lang, target_lang) DO UPDATE SET
                        translated_text=excluded.translated_text,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    batch,
                )
            self.conn.commit()

    def stats(self) -> dict[str, Any]:
        with self.lock:
            cur = self.conn.execute("SELECT COUNT(*) FROM translations")
            total = cur.fetchone()[0] or 0
            cur = self.conn.execute("SELECT MAX(updated_at) FROM translations")
            last = cur.fetchone()[0]
            cur = self.conn.execute("""
                SELECT source_lang, target_lang, COUNT(*) as cnt
                FROM translations
                GROUP BY source_lang, target_lang
                ORDER BY cnt DESC
                LIMIT 100
                """)
            pairs = cur.fetchall()
            pairs_list = [
                {"source": r[0], "target": r[1], "count": r[2]} for r in pairs
            ]
            return {
                "total_entries": total,
                "last_updated": last,
                "pairs": pairs_list,
            }

    def close(self) -> None:
        with self.lock:
            self.conn.commit()
            self.conn.close()


def translate_chunk(
    chunk: list[str],
    source_lang: str,
    target_lang: str,
) -> tuple[list[str], str | None]:
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


def save_progress(
    all_lines: list[str],
    results: dict[str, str],
    output_path: Path,
    json_path: Path,
    source_lang: str,
    target_lang: str,
    output_type: str = "json",
) -> None:
    """
    Persist translation progress.

    output_type:
      - "text":   translated text file only; untranslated lines keep original.
      - "json":   structured JSON with metadata + translations map.
      - "merged": paired text file — each source line followed by its
                  translation. If no translation exists, or the translation
                  equals the source, a blank line is written instead.
    """
    try:
        translated_count = sum(1 for line in all_lines if line in results)

        if output_type == "text":
            with output_path.open("w", encoding="utf-8") as f:
                for line in all_lines:
                    if line in results:
                        f.write(f"{results[line]}\n")
                    else:
                        f.write(f"{line}\n")
            saved_name = output_path.name
            shown_translated = translated_count

        elif output_type == "json":
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
            saved_name = json_path.name
            shown_translated = translated_count

        elif output_type == "merged":
            shown_translated = 0
            with output_path.open("w", encoding="utf-8") as f:
                for line in all_lines:
                    f.write(f"{line}\n")
                    if line in results:
                        tgt = results[line]
                        # If the translator returned the original (or empty),
                        # write a blank line for it.
                        if not tgt or tgt == line:
                            f.write("\n")
                        else:
                            f.write(f"{tgt}\n")
                            shown_translated += 1
                    else:
                        f.write("\n")
            saved_name = output_path.name

        else:
            logger.error("Unknown output type: {}", output_type)
            return

        print(
            f"Progress saved: {shown_translated}/{len(all_lines)} lines translated "
            f"(Output: {saved_name})"
        )
    except Exception as e:
        logger.error("Error saving progress: {}", e)


def main() -> None:
    global interrupted
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(
        description="Translate lines in a text file with persistent caching and progress saving."
    )
    parser.add_argument("-i", "--input", help="Input text file (one phrase per line)")
    parser.add_argument(
        "-s", "--source", default="ru", help="Source language code (default: ru)"
    )
    parser.add_argument(
        "-t", "--target", default="en", help="Target language code (default: en)"
    )
    parser.add_argument(
        "-o",
        "--output-type",
        choices=["text", "json", "merged"],
        default="json",
        help=(
            "Output type: "
            "'text' (translated lines only), "
            "'json' (structured JSON), "
            "'merged' (source line + translation line pairs). "
            "Default: json"
        ),
    )
    parser.add_argument(
        "--db",
        default="~/.translate/translate.db",
        help="SQLite DB path for cache (default: ~/.translate/translate.db)",
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
    parser.add_argument(
        "--cache-stats", action="store_true", help="Show cache statistics and exit"
    )
    args = parser.parse_args()

    db_path = Path(os.path.expanduser(args.db))
    cache = TranslationCache(db_path)

    if args.cache_stats:
        stats = cache.stats()
        print("Translation cache stats")
        print("-----------------------")
        print(f"DB path: {db_path}")
        print(f"Total entries: {stats['total_entries']}")
        print(f"Last updated: {stats['last_updated']}")
        print("Top language pairs:")
        if stats["pairs"]:
            for p in stats["pairs"]:
                print(f"  {p['source']} -> {p['target']}: {p['count']}")
        else:
            print("  (no entries)")
        cache.close()
        return

    if not args.input:
        parser.error(
            "the following arguments are required: -i/--input (unless --cache-stats is used)"
        )

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        cache.close()
        return

    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.rstrip("\n") for w in f if w.strip() != ""]
    except Exception as e:
        logger.error("Error reading input file: {}", e)
        cache.close()
        return

    if not all_lines:
        print(f"No non-empty lines found in {input_path.name}")
        cache.close()
        return

    source_lang = args.source
    target_lang = args.target

    if source_lang.lower() == "ru" or source_lang.lower().startswith("ru"):
        to_translate_raw = [line for line in all_lines if contains_cyrillic(line)]
        skipped_lines = [line for line in all_lines if not contains_cyrillic(line)]
    else:
        to_translate_raw = list(all_lines)
        skipped_lines = []

    print(
        f"Loaded {len(all_lines)} lines: "
        f"{len(to_translate_raw)} flagged for translation, "
        f"{len(skipped_lines)} skipped"
    )

    if not to_translate_raw:
        print(f"No lines to translate for source_lang={source_lang}")
        cache.close()
        return

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

    cached = cache.get_many(to_translate_unique, source_lang, target_lang)
    print(f"Cache hit: {len(cached)}/{len(to_translate_unique)}")

    results: dict[str, str] = dict(cached)
    remaining_to_translate = [
        line for line in to_translate_unique if line not in results
    ]

    output_path = input_path.with_name(
        f"{input_path.stem}_{target_lang}{input_path.suffix}"
    )
    json_path = input_path.with_name(f"{input_path.stem}_{target_lang}.json")

    save_progress(
        all_lines,
        results,
        output_path,
        json_path,
        source_lang,
        target_lang,
        args.output_type,
    )

    if remaining_to_translate and not interrupted:
        chunks = create_chunks(remaining_to_translate, args.max_chunk_size)
        num_workers = min(max(1, args.max_workers), len(chunks))
        print(
            f"Created {len(chunks)} chunk(s) from {len(remaining_to_translate)} "
            f"remaining lines (max {args.max_chunk_size} chars per chunk), "
            f"using {num_workers} worker(s)"
        )

        last_save_time = time.time()
        save_lock = threading.Lock()

        def periodic_save() -> None:
            """Background thread that periodically saves translation progress to disk."""
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
                            args.output_type,
                        )
                        last_save_time = time.time()

        save_thread = threading.Thread(target=periodic_save, daemon=True)
        save_thread.start()

        try:
            with mp.Pool(processes=num_workers) as pool:
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
                to_cache: dict[str, str] = {}

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
                                for i, original_line in enumerate(original_lines):
                                    tgt = translated_lines[i]
                                    results[original_line] = tgt
                                    to_cache[original_line] = tgt
                            else:
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
                                        to_cache[line] = t
                                    except Exception as e:
                                        logger.error(
                                            "Per-line fallback failed for '{}': {}",
                                            line[:50],
                                            e,
                                        )
                                        results[line] = line
                                        to_cache[line] = line
                            sample_src = (
                                original_lines[0][:40]
                                + ("..." if len(original_lines[0]) > 40 else "")
                                if original_lines
                                else ""
                            )
                            sample_tgt = results.get(
                                original_lines[0] if original_lines else "", ""
                            )[:60]
                            print(
                                f"Translated chunk {completed}/{total} "
                                f"(sample: '{sample_src}' → '{sample_tgt}')"
                            )
                            if len(to_cache) >= 50 or completed == total:
                                cache.set_many(to_cache, source_lang, target_lang)
                                to_cache.clear()
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
                                        to_cache[line] = t
                                    except Exception as e:
                                        logger.error(
                                            "Per-line retry failed for '{}': {}",
                                            line[:50],
                                            e,
                                        )
                                        results[line] = line
                                        to_cache[line] = line
                    except Exception as e:
                        if not interrupted:
                            logger.error(
                                "Unexpected error processing chunk starting with '{}': {}",
                                (chunk[0][:60] + "...") if chunk else "",
                                e,
                            )

                    if time.time() - last_save_time >= args.save_interval:
                        with save_lock:
                            save_progress(
                                all_lines,
                                results,
                                output_path,
                                json_path,
                                source_lang,
                                target_lang,
                                args.output_type,
                            )
                            last_save_time = time.time()

                if to_cache and not interrupted:
                    cache.set_many(to_cache, source_lang, target_lang)
                    print(f"Saved {len(to_cache)} new translations to cache")

        except KeyboardInterrupt:
            logger.warning("Keyboard interrupt detected. Saving progress...")
            interrupted = True
        except Exception as e:
            logger.error("Unexpected error: {}", e)

    save_progress(
        all_lines,
        results,
        output_path,
        json_path,
        source_lang,
        target_lang,
        args.output_type,
    )

    if interrupted:
        logger.warning("Process was interrupted. Progress has been saved.")
        print("You can resume by running the command again (cache will be used).")
    else:
        translated_count = sum(
            1 for line in all_lines if line in results and results[line] != line
        )
        print(
            f"Translation complete: {translated_count}/{len(all_lines)} "
            f"lines translated successfully"
        )

    cache.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user. Exiting...")
        sys.exit(1)
