#!/data/data/com.termux/files/home/.local/bin/python
"""
translate.py — Translate lines in a text file using deep_translator.GoogleTranslator
with graceful interrupt handling and periodic progress saving.

Features
--------
* Chunked batch translation inside each worker (TRANSLATE_CHUNK lines per API call).
* Automatic Cyrillic detection when source language is "ru" — lines without any
  Cyrillic characters are passed through unchanged (they're likely already not Russian).
* Periodic progress saving: writes the output text file plus a JSON metadata sidecar.
* Graceful SIGINT/SIGTERM handling; the pool is terminated and progress is flushed.
* Concurrent processing via multiprocessing.Pool.

Usage
-----
    python translate.py -i input.txt -s ru -t en
    python translate.py -i input.txt -s ru -t en --workers 8 --batch-size 200
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
from queue import Empty, Queue

try:
    from deep_translator import GoogleTranslator
except ImportError:  # pragma: no cover
    sys.stderr.write("Missing dependency: pip install deep-translator\n")
    raise


# ---------------------------------------------------------------------------
# Configuration / globals
# ---------------------------------------------------------------------------

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
TRANSLATE_CHUNK = 20  # lines per GoogleTranslator API call inside a worker
DEFAULT_SAVE_INTERVAL = 10.0  # seconds between periodic saves

_shutdown = False  # set by signal handler (main process only)


def _has_cyrillic(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text))


def _handle_signal(signum, _frame) -> None:
    global _shutdown
    _shutdown = True
    sys.stderr.write(f"\n[translate] received signal {signum}, finishing up...\n")


# ---------------------------------------------------------------------------
# Worker functions (run inside the multiprocessing pool)
# ---------------------------------------------------------------------------


def _translate_texts(texts: list[str], src: str, tgt: str) -> list[str]:
    """Call GoogleTranslator.translate_batch and validate the result."""
    translator = GoogleTranslator(source=src, target=tgt)
    result = translator.translate_batch(texts)
    if not result or len(result) != len(texts):
        raise RuntimeError(
            f"translate_batch returned unexpected result (got {result!r})"
        )
    return [r if r is not None else t for r, t in zip(result, texts)]


def _translate_task(
    task: tuple[str, str, list[tuple[int, str]]],
) -> list[tuple[int, str]]:
    """Translate a batch of (index, text) items."""
    src, tgt, items = task

    results: list[tuple[int, str]] = []
    pending: list[tuple[int, str]] = []

    for idx, text in items:
        if not text.strip():
            results.append((idx, text))
            continue
        # When source is Russian, pass through anything without Cyrillic.
        if src == "ru" and not _has_cyrillic(text):
            results.append((idx, text))
            continue
        pending.append((idx, text))

    for i in range(0, len(pending), TRANSLATE_CHUNK):
        batch = pending[i : i + TRANSLATE_CHUNK]
        texts = [t for _, t in batch]
        try:
            translated = _translate_texts(texts, src, tgt)
        except Exception as exc:  # noqa: BLE001 — keep going on any API failure
            sys.stderr.write(f"[translate] batch failed ({exc}); keeping originals\n")
            translated = texts

        for (idx, _original), tr in zip(batch, translated):
            results.append((idx, tr))

    return results


# ---------------------------------------------------------------------------
# Progress saving
# ---------------------------------------------------------------------------


def _save_progress(
    output_path: str,
    meta_path: str,
    lines: list[str],
    translations: dict[int, str],
    src: str,
    tgt: str,
    input_path: Path,
    complete: bool = False,
) -> None:
    """Atomically write the partial (or final) output text + JSON metadata."""
    out_lines = [translations.get(i, lines[i]) for i in range(len(lines))]

    tmp_out = output_path + ".tmp"
    Path(tmp_out).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.replace(tmp_out, output_path)

    meta = {
        "input": str(input_path),
        "output": output_path,
        "source_lang": src,
        "target_lang": tgt,
        "total_lines": len(lines),
        "translated_lines": len(translations),
        "complete": complete,
        "updated_at": time.time(),
    }
    tmp_meta = meta_path + ".tmp"
    Path(tmp_meta).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp_meta, meta_path)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_translate(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    if not input_path.is_file():
        sys.exit(f"Input file not found: {input_path}")

    lines = input_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        sys.exit("Input file is empty")

    output_path = args.output or str(input_path) + ".translated.txt"
    meta_path = output_path + ".meta.json"

    # Build tasks: each task carries a slice of (index, text) tuples.
    indexed = list(enumerate(lines))
    batch_size = max(1, args.batch_size)
    batches = [indexed[i : i + batch_size] for i in range(0, len(indexed), batch_size)]
    tasks = [(args.source, args.target, b) for b in batches]

    translations: dict[int, str] = {}
    last_save = time.time()

    # Initial (empty) save so the user always has an output file to look at.
    _save_progress(
        output_path,
        meta_path,
        lines,
        translations,
        args.source,
        args.target,
        input_path,
    )

    print(
        f"[translate] {len(lines)} lines / {len(batches)} batches, "
        f"{args.workers} workers, src={args.source} tgt={args.target}",
        file=sys.stderr,
    )
    print(f"[translate] output : {output_path}", file=sys.stderr)

    result_queue: Queue = Queue()

    def _on_ok(res):
        result_queue.put(("ok", res))

    def _on_err(exc):
        result_queue.put(("err", exc))

    pool = Pool(processes=args.workers)

    try:
        for t in tasks:
            pool.apply_async(
                _translate_task, (t,), callback=_on_ok, error_callback=_on_err
            )

        pending = len(tasks)
        while pending > 0:
            if _shutdown:
                break
            try:
                status, payload = result_queue.get(timeout=0.5)
            except Empty:
                continue
            pending -= 1

            if status == "ok":
                translations.update(dict(payload))
            else:
                sys.stderr.write(f"[translate] task failed: {payload}\n")

            now = time.time()
            if now - last_save >= args.save_interval:
                _save_progress(
                    output_path,
                    meta_path,
                    lines,
                    translations,
                    args.source,
                    args.target,
                    input_path,
                )
                done = len(translations)
                pct = 100.0 * done / len(lines)
                print(
                    f"[translate] progress: {done}/{len(lines)} ({pct:.1f}%)",
                    file=sys.stderr,
                )
                last_save = now

    except KeyboardInterrupt:
        _shutdown = True
    finally:
        pool.terminate()
        pool.join()

        complete = (not _shutdown) and len(translations) == len(lines)
        _save_progress(
            output_path,
            meta_path,
            lines,
            translations,
            args.source,
            args.target,
            input_path,
            complete=complete,
        )

    done = len(translations)
    tag = "complete" if complete else "interrupted"
    print(
        f"[translate] {tag}: wrote {output_path} ({done}/{len(lines)} lines)",
        file=sys.stderr,
    )
    if not complete:
        sys.exit(130 if _shutdown else 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Translate a text file with deep_translator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-i", "--input", help="Path to the input text file.")
    p.add_argument(
        "-s",
        "--source",
        default="auto",
        help="Source language code (e.g. 'ru', 'en', 'auto').",
    )
    p.add_argument(
        "-t", "--target", default="en", help="Target language code (e.g. 'en')."
    )
    p.add_argument(
        "-o", "--output", help="Output file path (default: <input>.translated.txt)."
    )
    p.add_argument(
        "--workers",
        type=int,
        default=min(4, cpu_count() or 1),
        help="Number of worker processes.",
    )
    p.add_argument(
        "--batch-size", type=int, default=100, help="Number of lines per worker task."
    )
    p.add_argument(
        "--save-interval",
        type=float,
        default=DEFAULT_SAVE_INTERVAL,
        help="Seconds between periodic progress saves.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Install signal handlers in the main process only (workers ignore SIGINT).
    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    if not args.input:
        parser.error("--input/-i is required")

    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    cmd_translate(args)


if __name__ == "__main__":
    main()
