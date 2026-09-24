#!/data/data/com.termux/files/home/.local/bin/python
"""
translate_words.py
==================

Translate a word-list file (one word per line) into a JSON mapping, using the
first *usable* translation backend from a priority list.

Features
--------
* Backends tried in order: ``translate`` -> ``deep_translator`` -> ``googletrans``.
  If the preferred backend cannot be imported or initialized, the script
  automatically falls back to the next one and prints which backend was used.
* The ``translate`` backend accepts both ``translate.Translator`` (upstream
  PyPI) and ``translate.GoogleTranslator`` (forks / bundled distributions).
* Detects the common footgun of a local ``translate.py`` shadowing the real
  package.
* Rejects "identity translations": if the backend returns the input unchanged,
  the word is treated as a failure and retried.
* Up to 3 attempts per word with exponential backoff.
* Words that fail all attempts are written to ``failed.txt`` (one per line)
  and never written to the output JSON.
* Live console output prints the raw translation result as received.
* Structured error logging via ``loguru`` (console + ``translate_words.log``).
* Concurrency via a thread pool (``-w``).
* Per-request delay to avoid rate limits (``-d``).
* Periodic *atomic* JSON saves (``--save-every``).
* Automatic resume: words already in the output file are skipped.
* Graceful Ctrl+C: saves progress before exiting.

Usage
-----
    python translate_words.py -i words.txt -t en -b deep_translator
    python translate_words.py -i words.txt -o out.json -s fr -t es -w 8 -d 0.1
    python translate_words.py -i words.txt --no-continue
"""

import argparse
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
# Remove loguru's default stderr sink and install two of our own:
#   * a plain-text file sink (rotating) for post-mortem analysis
#   * a compact stderr sink for live visibility
# Console output of translations is handled separately by our own prints so
# loguru messages don't get mixed with the progress stream.

logger.remove()
logger.add(
    "translate_words.log",
    level="DEBUG",
    rotation="10 MB",
    retention=5,
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {thread.name} | {message}",
)
logger.add(
    sys.stderr,
    level="ERROR",
    format="<red>{level}</red>: {message}",
)


# ---------------------------------------------------------------------------
# Backend configuration
# ---------------------------------------------------------------------------

#: Backends we know how to talk to, in the order we try them when the user's
#: preferred backend cannot be initialized (automatic fallback).
FALLBACK_ORDER = ("translate", "deep_translator", "googletrans")

#: How many attempts per word before we give up and log it as failed.
MAX_RETRIES = 3


class BackendError(Exception):
    """Raised when a backend cannot be imported, initialized, or used."""


# ---------------------------------------------------------------------------
# Per-backend factory functions
# ---------------------------------------------------------------------------
# Every `_make_<backend>` returns a callable ``(text: str) -> str`` on success,
# or raises ``BackendError``. The returned callable may close over any state it
# needs (a lock, a cached translator instance, etc.), so the wrapper stays
# agnostic of each library's particular API.


def _make_translate(source, target, script_path):
    """
    Backend: PyPI package ``translate``.

    Upstream exposes ``translate.Translator``; some forks and bundled builds
    expose ``translate.GoogleTranslator`` instead. We accept either, and we
    also guard against a local file silently shadowing the real package.
    """
    try:
        import translate
    except ImportError as e:
        raise BackendError(f"cannot import 'translate': {e}")

    # Guard: if `translate` resolves to *this* script, the user probably named
    # their file `translate.py`, which shadows the real package.
    mod_file = os.path.abspath(getattr(translate, "__file__", "") or "")
    if mod_file and mod_file == os.path.abspath(script_path):
        raise BackendError(
            "'translate' resolves to this script itself "
            "(rename the script to avoid shadowing the package)"
        )

    # Pick whichever translator class the module actually exposes.
    cls = getattr(translate, "Translator", None) or getattr(
        translate, "GoogleTranslator", None
    )
    if cls is None:
        raise BackendError(
            "'translate' module exposes neither 'Translator' nor 'GoogleTranslator'"
        )

    if cls.__name__ == "Translator":
        # Upstream API: from_lang / to_lang
        def call(text, cls=cls, source=source, target=target):
            return cls(from_lang=source, to_lang=target).translate(text)
    else:
        # GoogleTranslator-style API: source / target
        def call(text, cls=cls, source=source, target=target):
            return cls(source=source, target=target).translate(text)

    return call


def _make_deep_translator(source, target, _script_path):
    """Backend: PyPI package ``deep_translator`` (GoogleTranslator)."""
    try:
        from deep_translator import GoogleTranslator
    except ImportError as e:
        raise BackendError(f"cannot import 'deep_translator': {e}")

    def call(text, cls=GoogleTranslator, source=source, target=target):
        # Fresh instance per call keeps the API thread-safe.
        return cls(source=source, target=target).translate(text)

    return call


def _make_googletrans(source, target, _script_path):
    """
    Backend: PyPI package ``googletrans``.

    ``googletrans.Translator`` is not documented as thread-safe, so we reuse a
    single instance and serialize every call through a lock.
    """
    try:
        from googletrans import Translator
    except ImportError as e:
        raise BackendError(f"cannot import 'googletrans': {e}")

    lock = threading.Lock()
    inst = Translator()

    def call(text, inst=inst, lock=lock, source=source, target=target):
        with lock:
            return inst.translate(text, src=source, dest=target).text

    return call


#: Registry: backend name -> factory function.
_BACKEND_FACTORIES = {
    "translate": _make_translate,
    "deep_translator": _make_deep_translator,
    "googletrans": _make_googletrans,
}


# ---------------------------------------------------------------------------
# Unified translator wrapper
# ---------------------------------------------------------------------------


class TranslatorWrapper:
    """
    Resolve the preferred backend, silently falling back to the others on
    failure. Once constructed, ``.translate(text)`` dispatches to the
    selected backend.

    Attributes
    ----------
    backend_name : str
        The backend that was actually chosen (may differ from the preferred
        one if automatic fallback occurred).
    """

    def __init__(self, preferred, source, target, script_path):
        self.source = source
        self.target = target
        self.backend_name = None
        self._call = None

        # Preferred backend first, then the rest of FALLBACK_ORDER.
        candidates = [preferred] + [b for b in FALLBACK_ORDER if b != preferred]

        errors = []
        for name in candidates:
            factory = _BACKEND_FACTORIES.get(name)
            if factory is None:
                errors.append((name, "unknown backend"))
                continue
            try:
                self._call = factory(source, target, script_path)
            except BackendError as e:
                errors.append((name, str(e)))
                logger.warning("Backend '{}' unavailable: {}", name, e)
                continue

            # Success.
            self.backend_name = name
            if name != preferred:
                print(
                    f"⚠️  Backend '{preferred}' unavailable — falling back to '{name}'."
                )
            logger.info("Using backend '{}'", name)
            return

        # No backend could be initialized: helpful diagnostic.
        print("Error: no usable translation backend found.", file=sys.stderr)
        for name, err in errors:
            print(f"  - {name}: {err}", file=sys.stderr)
            logger.error("Backend '{}' failed: {}", name, err)
        print("\nInstall at least one of:", file=sys.stderr)
        print("  pip install translate", file=sys.stderr)
        print("  pip install deep_translator", file=sys.stderr)
        print("  pip install googletrans==4.0.0rc1", file=sys.stderr)
        sys.exit(1)

    def translate(self, text):
        """Translate a single piece of text with the selected backend."""
        return self._call(text)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def load_progress(out_path):
    """
    Load an existing output JSON file so a previous job can be resumed.

    Returns an empty dict when the file does not exist, cannot be parsed, or
    does not contain a JSON object.
    """
    if not os.path.exists(out_path):
        return {}
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Could not read existing output file {}: {}", out_path, e)
    return {}


def save_output(out_path, data, lock):
    """
    Atomically write ``data`` to ``out_path`` as pretty JSON.

    We write to a temp file and then rename it, so an interrupted write can
    never leave a half-written (i.e. corrupt) JSON file on disk.
    """
    with lock:
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, out_path)  # atomic on POSIX and Windows


def append_failed(failed_path, word, lock):
    """Append a single failed word to ``failed.txt`` (thread-safe)."""
    with lock:
        with open(failed_path, "a", encoding="utf-8") as f:
            f.write(word + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Translate a word list file line by line to JSON."
    )
    # Input / output -------------------------------------------------------
    parser.add_argument(
        "-i",
        "--input",
        default="words.txt",
        help="Input file with one word per line (default: words.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="words.json",
        help="Output JSON file (default: words.json)",
    )
    parser.add_argument(
        "--failed",
        default="failed.txt",
        help="File collecting words that failed all retries (default: failed.txt)",
    )
    # Languages ------------------------------------------------------------
    parser.add_argument(
        "-s", "--source", default="fr", help="Source language code (default: fr)"
    )
    parser.add_argument(
        "-t", "--target", default="en", help="Target language code (default: en)"
    )
    # Backend --------------------------------------------------------------
    parser.add_argument(
        "-b",
        "--backend",
        default="translate",
        choices=FALLBACK_ORDER,
        help="Preferred translation backend (default: translate); "
        "falls back automatically if unusable",
    )
    # Concurrency / rate limiting -----------------------------------------
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent worker threads (default: 4)",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0.3,
        help="Delay in seconds between requests per worker (default: 0.3)",
    )
    # Saving / resume ------------------------------------------------------
    parser.add_argument(
        "--save-every",
        type=int,
        default=100,
        help="Save the output file every N words (default: 100)",
    )
    parser.add_argument(
        "--no-continue",
        action="store_true",
        help="Do not resume from a previous job; start from scratch",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()

    input_path = args.input
    out_path = args.output
    failed_path = args.failed

    # -- Validate input -----------------------------------------------------
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)

    # -- Read words (strip blanks and whitespace) ---------------------------
    with open(input_path, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    print(f"Loaded {len(words)} words from {input_path}")
    print(f"Source -> target: {args.source} -> {args.target}")

    # -- Load existing progress (unless --no-continue) ----------------------
    results = {} if args.no_continue else load_progress(out_path)
    if results:
        print(f"Resuming: {len(results)} words already translated.")

    # -- Figure out what still needs translating ----------------------------
    pending = [w for w in words if w not in results]

    if not pending:
        print("Nothing to translate. Done.")
        return

    # -- Set up translator (with fallback) ----------------------------------
    translator = TranslatorWrapper(
        preferred=args.backend,
        source=args.source,
        target=args.target,
        script_path=__file__,
    )
    print(
        f"Backend: {translator.backend_name} | "
        f"Workers: {args.workers} | Delay: {args.delay}s | "
        f"Save every: {args.save_every} | Retries: {MAX_RETRIES}"
    )
    print(f"Words to translate: {len(pending)}")

    # -- Shared state -------------------------------------------------------
    save_lock = threading.Lock()  # protects atomic file writes
    counter_lock = threading.Lock()  # protects completed_count
    print_lock = threading.Lock()  # keeps console output readable
    failed_lock = threading.Lock()  # protects failed.txt appends
    completed_count = [0]  # mutable list avoids `nonlocal`
    total_pending = len(pending)

    # -- Worker function ----------------------------------------------------
    def translate_word(word):
        """
        Try up to ``MAX_RETRIES`` times to translate one word.

        A retry is triggered by:
          * an exception raised by the backend, or
          * an "identity translation": the backend returned the input
            unchanged (a common failure mode when a term is unknown or the
            service silently returned the source text).

        On success returns ``(word, translation)``. On persistent failure
        returns ``(word, None)`` — the caller appends the word to
        ``failed.txt`` and skips it in the output JSON.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                time.sleep(args.delay)  # per-request rate-limit delay

                raw = translator.translate(word)
                text = "" if raw is None else str(raw).strip()

                # Reject identity translations (input returned unchanged,
                # case-insensitively) and empty responses.
                if not text:
                    raise ValueError("empty translation")
                if text.casefold() == word.casefold():
                    raise ValueError(f"identity translation returned: {text!r}")

                # Success — report the raw result.
                with print_lock:
                    print(f"  → {word!r} returned {text!r}")
                return word, text

            except Exception as e:
                logger.warning(
                    "Attempt {}/{} failed for {!r}: {}",
                    attempt,
                    MAX_RETRIES,
                    word,
                    e,
                )
                if attempt < MAX_RETRIES:
                    # Gentle exponential backoff before retrying.
                    time.sleep(args.delay * (attempt + 1))

        # All attempts exhausted.
        logger.error("All {} attempts failed for {!r}", MAX_RETRIES, word)
        return word, None

    # -- Run the thread pool ------------------------------------------------
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(translate_word, w): w for w in pending}

            for future in as_completed(futures):
                word, translation = future.result()

                with counter_lock:
                    completed_count[0] += 1
                    count = completed_count[0]

                if translation is None:
                    # Exhausted retries — record to failed.txt, skip JSON.
                    append_failed(failed_path, word, failed_lock)
                    with print_lock:
                        print(
                            f"[{count}/{total_pending}] ✗ {word} "
                            f"(failed -> {failed_path})"
                        )
                else:
                    results[word] = translation
                    with print_lock:
                        print(f"[{count}/{total_pending}] ✓ {word} -> {translation}")

                # Periodic atomic save.
                if count % args.save_every == 0:
                    save_output(out_path, results, save_lock)
                    with print_lock:
                        print(f"  💾 Saved progress ({count}/{total_pending})")

    except KeyboardInterrupt:
        # Ctrl+C: flush what we have and exit cleanly.
        print("\n\n⚠️  Interrupted by user. Saving progress...")
        save_output(out_path, results, save_lock)
        print(f"Progress saved to {out_path}. Run again to resume.")
        logger.info("Interrupted by user; saved {} entries", len(results))
        sys.exit(0)

    # -- Final save ---------------------------------------------------------
    save_output(out_path, results, save_lock)
    print(f"\n✅ Done! Translated {len(results)} words total.")
    print(f"Output: {out_path}")
    if os.path.exists(failed_path):
        with open(failed_path, "r", encoding="utf-8") as f:
            failed_count = sum(1 for _ in f if _.strip())
        print(f"Failed words ({failed_count}): {failed_path}")


if __name__ == "__main__":
    main()
