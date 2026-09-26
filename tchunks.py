#!/data/data/com.termux/files/home/.local/bin/python
"""
Split a text file into fixed-size, word-boundary-respecting chunks,
translate each chunk through a pluggable backend, and write results to a
resumable JSON file.

Designed for Termux on Android 7 / armv8l (32-bit ARM), Python 3.12.
Avoids any backend or dependency that requires torch, ctranslate2,
sentencepiece, grpcio, pydantic-core, or an LLM SDK without pydantic<2,
since none of those reliably build/run on 32-bit ARM Termux.

Usage:
    python tchunks.py -i input.txt -o chunks.json -s en -t fr
    python tchunks.py -i input.txt -b deep_translator -w 2
    python tchunks.py --no-continue -i book.txt

Resume behavior:
    On startup, if the output JSON already exists (and --no-continue is
    not passed), it is loaded and any chunk index already present is
    skipped. This makes interrupted runs safe to simply re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import FrameType
from typing import Any

from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# --------------------------------------------------------------------------
# Custom exceptions
# --------------------------------------------------------------------------


class TranslationFailedError(Exception):
    """Raised when a backend call fails or returns an unusable result.

    Also raised (deliberately) when a translation looks like an identity
    passthrough (output ~= input), since several free backends silently
    echo the source text back instead of raising when something goes
    wrong server-side. Treating that as a failure lets tenacity retry it
    like any other transient error.
    """


class UnknownBackendError(Exception):
    """Raised when --backend names a backend not present in BACKEND_FACTORIES."""


class NoBackendAvailableError(Exception):
    """Raised when no backend could be selected via the fallback order,
    typically because none of the optional libraries are importable.
    """


# --------------------------------------------------------------------------
# Language code mapping
# --------------------------------------------------------------------------
# Each backend has its own expected language-code dialect (some want
# ISO 639-1 lowercase, some want upper-case, DeepL wants specific
# regional variants for a few languages). We normalize user input (assumed
# ISO 639-1, e.g. "en", "fr") to whatever each backend expects, rather than
# passing the raw CLI value straight through.

# DeepL requires upper-case target codes, and a few targets need a region
# suffix (e.g. "EN-US" vs "EN-GB"). We default ambiguous ones to a sane
# variant; users needing a specific region can extend this table.
_DEEPL_TARGET_OVERRIDES: dict[str, str] = {
    "en": "EN-US",
    "pt": "PT-PT",
    "zh": "ZH",
}


def _lang_for_deepl(code: str, *, is_target: bool) -> str:
    """Map an ISO 639-1 code to DeepL's expected format.

    DeepL wants upper-case codes for both source and target, but only
    target codes need the regional-variant overrides (source language is
    auto-detectable and less picky).
    """
    code = code.strip()
    if is_target and code.lower() in _DEEPL_TARGET_OVERRIDES:
        return _DEEPL_TARGET_OVERRIDES[code.lower()]
    return code.upper()


def _lang_for_deep_translator(code: str, *, is_target: bool) -> str:
    """deep_translator (GoogleTranslator etc.) wants lower-case ISO codes."""
    return code.strip().lower()


def _lang_for_translate_pkg(code: str, *, is_target: bool) -> str:
    """The `translate` package wants lower-case ISO codes."""
    return code.strip().lower()


def _lang_for_translators_bing(code: str, *, is_target: bool) -> str:
    """The `translators` package (Bing engine) wants lower-case ISO codes."""
    return code.strip().lower()


def _lang_for_googletrans(code: str, *, is_target: bool) -> str:
    """googletrans wants lower-case ISO codes."""
    return code.strip().lower()


def _lang_for_pygoogletranslation(code: str, *, is_target: bool) -> str:
    """pygoogletranslation (a googletrans fork) wants lower-case ISO codes."""
    return code.strip().lower()


# --------------------------------------------------------------------------
# Backend factories
# --------------------------------------------------------------------------
# Each factory takes (source, target) in raw user-provided form and returns
# a callable `translate(text: str) -> str`. The callable is expected to
# raise on failure; retry/backoff is applied by the caller via tenacity, not
# inside the factory itself, so factories stay simple and backend-agnostic.
#
# Clients are constructed fresh inside the returned callable (per call) for
# stateless/cheap-to-construct backends, which sidesteps thread-safety
# questions entirely. The two backends known to wrap a persistent,
# undocumented-thread-safety HTTP session (googletrans, pygoogletranslation)
# instead build one client at factory time and serialize access with a lock.


def _make_deepl(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `deepl` backend (official DeepL API, requires
    DEEPL_API_KEY environment variable). Pure Python, no compiled deps.
    """
    import deepl  # type: ignore[import-untyped]

    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise NoBackendAvailableError("DEEPL_API_KEY is not set")
    translator = deepl.Translator(api_key)
    src = _lang_for_deepl(source, is_target=False)
    tgt = _lang_for_deepl(target, is_target=True)

    def translate(text: str) -> str:
        result = translator.translate_text(text, source_lang=src, target_lang=tgt)
        return str(result.text)

    return translate


def _make_deep_translator(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `deep_translator` backend (GoogleTranslator by
    default). Pure Python HTTP client, no API key required, no compiled
    deps. This is the recommended default.
    """
    from deep_translator import GoogleTranslator  # type: ignore[import-untyped]

    src = _lang_for_deep_translator(source, is_target=False)
    tgt = _lang_for_deep_translator(target, is_target=True)

    def translate(text: str) -> str:
        # Build a fresh translator per call: GoogleTranslator is cheap to
        # construct and this avoids any doubt about thread-safety.
        client = GoogleTranslator(source=src, target=tgt)
        result = client.translate(text)
        if result is None:
            raise TranslationFailedError("deep_translator returned None")
        return str(result)

    return translate


def _make_translate(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `translate` package backend (Tier 2, free, fragile;
    rate-limited by the underlying MyMemory API).
    """
    from translate import Translator as TranslatePkgTranslator  # type: ignore[import-untyped]

    src = _lang_for_translate_pkg(source, is_target=False)
    tgt = _lang_for_translate_pkg(target, is_target=True)

    def translate(text: str) -> str:
        client = TranslatePkgTranslator(from_lang=src, to_lang=tgt)
        result = client.translate(text)
        if not result:
            raise TranslationFailedError("translate package returned empty result")
        return str(result)

    return translate


def _make_translators_bing(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `translators` package using the Bing engine
    (Tier 2, free, fragile; requires Node.js installed via `pkg install
    nodejs` for some translators internals).
    """
    import translators as ts  # type: ignore[import-untyped]

    src = _lang_for_translators_bing(source, is_target=False)
    tgt = _lang_for_translators_bing(target, is_target=True)

    def translate(text: str) -> str:
        result = ts.translate_text(
            text, translator="bing", from_language=src, to_language=tgt
        )
        if not result:
            raise TranslationFailedError("translators (bing) returned empty result")
        return str(result)

    return translate


# googletrans's Translator wraps an httpx/requests-like session whose
# thread-safety is not documented/guaranteed, so all calls through it are
# serialized with this lock rather than trusting concurrent access.
_googletrans_lock = threading.Lock()


def _make_googletrans(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `googletrans` backend (Tier 2, free, fragile; prone
    to breaking when Google changes internal endpoints). Access is
    serialized via a module-level lock since the client is not known to be
    thread-safe.
    """
    from googletrans import Translator as GoogleTransTranslator  # type: ignore[import-untyped]

    src = _lang_for_googletrans(source, is_target=False)
    tgt = _lang_for_googletrans(target, is_target=True)
    client = GoogleTransTranslator()

    def translate(text: str) -> str:
        with _googletrans_lock:
            result = client.translate(text, src=src, dest=tgt)
        if not result or not result.text:
            raise TranslationFailedError("googletrans returned empty result")
        return str(result.text)

    return translate


# Same thread-safety caveat as googletrans; this is a fork of it.
_pygoogletranslation_lock = threading.Lock()


def _make_pygoogletranslation(source: str, target: str) -> Callable[[str], str]:
    """Factory for the `pygoogletranslation` backend (Tier 2, free,
    fragile; a maintained fork of googletrans). Access is serialized via a
    module-level lock for the same reason as googletrans.
    """
    from pygoogletranslation import Translator as PyGoogleTranslator  # type: ignore[import-untyped]

    src = _lang_for_pygoogletranslation(source, is_target=False)
    tgt = _lang_for_pygoogletranslation(target, is_target=True)
    client = PyGoogleTranslator()

    def translate(text: str) -> str:
        with _pygoogletranslation_lock:
            result = client.translate(text, src=src, dest=tgt)
        if not result or not result.text:
            raise TranslationFailedError("pygoogletranslation returned empty result")
        return str(result.text)

    return translate


# Registry mapping CLI-facing backend names to their factory functions.
# Tier 3 cloud backends (boto3/baidu/alibaba/watson/azure) are intentionally
# not wired in here: each requires its own account setup, credential
# format, and API shape that a single generic factory can't cover safely
# without guessing at credentials env-var names. Add a `_make_<name>`
# factory following the pattern above and register it below to enable one.
BACKEND_FACTORIES: dict[str, Callable[[str, str], Callable[[str], str]]] = {
    "deepl": _make_deepl,
    "deep_translator": _make_deep_translator,
    "translate": _make_translate,
    "translators_bing": _make_translators_bing,
    "googletrans": _make_googletrans,
    "pygoogletranslation": _make_pygoogletranslation,
}

# Order used when --backend is not given: prefer deepl only if an API key
# is present (checked at selection time), then fall back through
# progressively more fragile free backends.
FALLBACK_ORDER: tuple[str, ...] = (
    "deepl",
    "deep_translator",
    "translate",
    "translators_bing",
    "googletrans",
    "pygoogletranslation",
)


def select_backend(
    requested: str | None, source: str, target: str
) -> tuple[str, Callable[[str], str]]:
    """Resolve the backend to use and construct its translate callable.

    If `requested` is given, it must be a key in BACKEND_FACTORIES or
    UnknownBackendError is raised immediately (fail fast on typos rather
    than silently falling back). If not given, walks FALLBACK_ORDER and
    returns the first backend that imports and constructs successfully
    (skipping `deepl` unless DEEPL_API_KEY is set).

    Returns:
        (backend_name, translate_callable)

    Raises:
        UnknownBackendError: `requested` is not a recognized backend name.
        NoBackendAvailableError: no backend in the fallback order could be
            constructed (e.g. none of the optional libraries are installed).
    """
    if requested:
        if requested not in BACKEND_FACTORIES:
            valid = ", ".join(sorted(BACKEND_FACTORIES))
            raise UnknownBackendError(
                f"unknown backend '{requested}'. Valid options: {valid}"
            )
        factory = BACKEND_FACTORIES[requested]
        translate_fn = factory(source, target)
        return requested, translate_fn

    last_error: Exception | None = None
    for name in FALLBACK_ORDER:
        if name == "deepl" and not os.environ.get("DEEPL_API_KEY"):
            logger.debug("Skipping deepl in fallback: DEEPL_API_KEY not set")
            continue
        try:
            factory = BACKEND_FACTORIES[name]
            translate_fn = factory(source, target)
            logger.debug(f"Selected backend via fallback order: {name}")
            return name, translate_fn
        except Exception as e:  # noqa: BLE001 - deliberately broad: trying each backend
            logger.debug(f"Backend '{name}' unavailable during fallback: {e}")
            last_error = e
            continue

    raise NoBackendAvailableError(
        f"no backend could be constructed from fallback order {FALLBACK_ORDER}. "
        f"Last error: {last_error}"
    )


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split `text` into chunks of at most `chunk_size` characters, breaking
    on whitespace where possible so words are not split mid-token.

    Algorithm: repeatedly take a window of up to `chunk_size` characters
    from the remaining text. If the window doesn't reach the end of the
    text, scan backwards from the end of the window for the last
    whitespace character and cut there instead, so the next chunk doesn't
    start mid-word. If no whitespace is found in the window (e.g. one
    extremely long token), fall back to a hard cut at `chunk_size`.

    Each resulting chunk has leading/trailing whitespace stripped. Chunks
    that are empty after stripping are omitted entirely (e.g. runs of
    blank lines between paragraphs).

    Args:
        text: Full input text.
        chunk_size: Maximum characters per chunk.

    Returns:
        Ordered list of non-empty, stripped chunk strings.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    chunks: list[str] = []
    pos = 0
    length = len(text)

    while pos < length:
        end = min(pos + chunk_size, length)
        if end < length:
            # Not at the end of the text: try to avoid splitting mid-word
            # by backing up to the last whitespace character in [pos, end).
            split_at = text.rfind(" ", pos, end)
            # Also consider newlines/tabs as valid break points.
            for ws_char in ("\n", "\t"):
                candidate = text.rfind(ws_char, pos, end)
                if candidate > split_at:
                    split_at = candidate
            if split_at > pos:
                end = split_at
            # else: no whitespace found in the window; hard-cut at chunk_size.

        piece = text[pos:end].strip()
        if piece:
            chunks.append(piece)
        pos = end

        # Skip over the whitespace we just split on so the next chunk
        # doesn't start with it (strip() above already handles this for
        # the piece itself, but pos must also advance past it).
        while pos < length and text[pos] in " \t\n\r":
            pos += 1

    return chunks


# --------------------------------------------------------------------------
# Identity-translation detection
# --------------------------------------------------------------------------


def _normalize_for_comparison(s: str) -> str:
    """Lower-case and collapse whitespace, for comparing source vs.
    translated text to detect identity (untranslated) passthroughs.
    """
    return " ".join(s.lower().split())


def looks_untranslated(
    source_text: str, translated_text: str, source_lang: str, target_lang: str
) -> bool:
    """Heuristically decide whether `translated_text` looks like the
    backend simply echoed `source_text` back unchanged, rather than
    performing an actual translation.

    Skipped entirely when source_lang == target_lang, since a genuinely
    identical result is expected and correct in that case.

    Comparison is case-insensitive and whitespace-collapsed to avoid false
    positives from incidental capitalization/formatting differences that a
    real translation might still introduce.
    """
    if source_lang.strip().lower() == target_lang.strip().lower():
        return False
    return _normalize_for_comparison(source_text) == _normalize_for_comparison(
        translated_text
    )


# --------------------------------------------------------------------------
# Retry wrapper
# --------------------------------------------------------------------------


def translate_with_retry(
    translate_fn: Callable[[str], str],
    text: str,
    source_lang: str,
    target_lang: str,
    delay: float,
) -> str:
    """Translate `text` with up to 3 attempts and exponential backoff,
    using tenacity. Also retries when the result looks like an identity
    passthrough (see `looks_untranslated`), since that pattern indicates a
    silent backend failure on several free services rather than a genuine
    translation.

    A fixed `delay` is applied *before* every attempt (including the
    first) to keep steady-state request pacing under `--delay`, separate
    from tenacity's exponential backoff between retries.

    Raises:
        TranslationFailedError: all 3 attempts failed or kept returning an
            identity passthrough.
    """

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(TranslationFailedError),
    )
    def _attempt() -> str:
        time.sleep(delay)
        try:
            result = translate_fn(text)
        except TranslationFailedError:
            raise
        except Exception as e:  # noqa: BLE001 - normalize any backend error to our type
            raise TranslationFailedError(f"backend call raised: {e}") from e

        if not result or not result.strip():
            raise TranslationFailedError("backend returned empty translation")

        if looks_untranslated(text, result, source_lang, target_lang):
            raise TranslationFailedError(
                "translation looks identical to source (likely untranslated)"
            )

        return result

    return _attempt()


# --------------------------------------------------------------------------
# Atomic JSON persistence
# --------------------------------------------------------------------------


def load_existing_results(output_path: Path) -> dict[str, str]:
    """Load previously saved translations from `output_path`, if it exists
    and is valid JSON. Returns an empty dict on any read/parse failure
    (logged, not raised) so a corrupted or missing output file never
    blocks a fresh run.
    """
    if not output_path.exists():
        return {}
    try:
        with output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"{output_path} did not contain a JSON object; ignoring")
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load existing output {output_path}: {e}")
        return {}


def save_results_atomic(output_path: Path, results: dict[str, str]) -> None:
    """Write `results` to `output_path` atomically: serialize to a
    temporary file in the same directory, flush and fsync it, then rename
    it over the destination. The rename is atomic on POSIX filesystems
    (including Termux's), so a crash mid-write never leaves a half-written
    JSON file at `output_path`.

    Keys are sorted numerically so the JSON file reads in chunk order
    regardless of dict insertion order (threads may complete out of
    sequence).
    """
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    ordered = {str(k): results[str(k)] for k in sorted(results, key=lambda k: int(k))}
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(ordered, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(output_path)
    finally:
        # If replace() succeeded, tmp_path no longer exists. If it failed,
        # clean up the leftover temp file so it doesn't linger.
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def append_failed_index(failed_path: Path, index: int) -> None:
    """Append a failed chunk index to the failed-chunks log file.

    Uses simple line-append rather than atomic rewrite: this file is
    advisory/diagnostic, and append-only writes are safe enough for that
    purpose without the overhead of a full atomic-rewrite scheme.
    """
    with failed_path.open("a", encoding="utf-8") as f:
        f.write(f"{index}\n")


# --------------------------------------------------------------------------
# Graceful shutdown handling
# --------------------------------------------------------------------------

# Set by the SIGINT handler; checked between chunk submissions/completions
# so Ctrl+C is honored promptly without needing to interrupt an in-flight
# network call.
_shutdown_requested = threading.Event()


def _handle_sigint(signum: int, frame: FrameType | None) -> None:
    """SIGINT handler: request shutdown rather than raising KeyboardInterrupt
    mid-stack, so in-flight futures can be drained and results saved
    cleanly instead of leaving the executor in an inconsistent state.
    """
    logger.info("Ctrl+C received, finishing in-flight chunks and saving...")
    _shutdown_requested.set()


# --------------------------------------------------------------------------
# Main translation loop
# --------------------------------------------------------------------------


def run_translation(
    chunks: list[str],
    existing: dict[str, str],
    translate_fn: Callable[[str], str],
    source_lang: str,
    target_lang: str,
    output_path: Path,
    failed_path: Path,
    workers: int,
    delay: float,
    save_every: int,
) -> dict[str, str]:
    """Translate all chunks not already present in `existing`, using a
    ThreadPoolExecutor with up to `workers` threads, saving progress every
    `save_every` completed chunks and on shutdown.

    Returns the full results dict (existing + newly translated), which is
    also the final state written to `output_path`.
    """
    results = dict(existing)
    pending_indices = [i for i in range(len(chunks)) if str(i) not in results]

    if not pending_indices:
        logger.info("All chunks already translated; nothing to do.")
        return results

    logger.info(
        f"Translating {len(pending_indices)} of {len(chunks)} chunk(s) with {workers} worker(s)"
    )

    completed_since_save = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index: dict[Future[str], int] = {}
        for idx in pending_indices:
            future = executor.submit(
                translate_with_retry,
                translate_fn,
                chunks[idx],
                source_lang,
                target_lang,
                delay,
            )
            future_to_index[future] = idx

        # as_completed-style draining, but written manually so we can check
        # _shutdown_requested between results rather than only at the end.
        remaining = set(future_to_index)
        while remaining:
            if _shutdown_requested.is_set():
                logger.info(
                    f"Shutdown requested: cancelling {len(remaining)} pending chunk(s)"
                )
                for fut in remaining:
                    fut.cancel()
                break

            done_now: set[Future[str]] = set()
            for fut in list(remaining):
                if fut.done():
                    done_now.add(fut)

            if not done_now:
                # Avoid a busy-spin; short sleep between polling passes.
                time.sleep(0.1)
                continue

            for fut in done_now:
                idx = future_to_index[fut]
                try:
                    translated = fut.result()
                    results[str(idx)] = translated
                    logger.debug(f"Chunk {idx} translated ({len(translated)} chars)")
                except Exception as e:  # noqa: BLE001 - any failure -> log + record as failed
                    logger.error(f"Chunk {idx} failed after retries: {e}")
                    append_failed_index(failed_path, idx)

                completed_since_save += 1
                remaining.discard(fut)

                if completed_since_save >= save_every:
                    save_results_atomic(output_path, results)
                    completed_since_save = 0
                    logger.debug(
                        f"Progress saved ({len(results)}/{len(chunks)} chunks)"
                    )

    # Final save covers both a clean finish and a shutdown-triggered break,
    # so no completed work is ever lost.
    save_results_atomic(output_path, results)
    logger.info(f"Saved {len(results)}/{len(chunks)} chunk(s) to {output_path}")
    return results


# --------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------


def configure_logging(log_file: Path) -> None:
    """Configure loguru: DEBUG-and-above to a rotating log file, ERROR-and-
    above to stderr. The default loguru stderr sink is removed first so
    DEBUG-level messages don't also spam the terminal.
    """
    logger.remove()
    logger.add(sys.stderr, level="ERROR", backtrace=False, diagnose=False)
    logger.add(
        log_file,
        level="DEBUG",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Define and parse command-line arguments."""
    ap = argparse.ArgumentParser(
        description="Split a text file into chunks, translate each chunk, and save results to JSON.",
    )
    ap.add_argument(
        "-i", "--input", type=Path, default=Path("input.txt"), help="Input text file."
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("chunks.json"),
        help="Output JSON file.",
    )
    ap.add_argument(
        "--failed",
        type=Path,
        default=Path("failed.txt"),
        help="Failed chunk indices log.",
    )
    ap.add_argument(
        "-s", "--source", default="en", help="Source language code (ISO 639-1)."
    )
    ap.add_argument(
        "-t", "--target", default="fr", help="Target language code (ISO 639-1)."
    )
    ap.add_argument(
        "-b",
        "--backend",
        default=None,
        choices=sorted(BACKEND_FACTORIES),
        help="Translator backend. If omitted, tries the fallback order automatically.",
    )
    ap.add_argument(
        "-w",
        "--workers",
        type=int,
        default=2,
        help="Concurrent threads (keep <= 4 per memory constraints; default 2).",
    )
    ap.add_argument(
        "-d", "--delay", type=float, default=0.5, help="Seconds between requests."
    )
    ap.add_argument(
        "--chunk-size", type=int, default=2500, help="Characters per chunk."
    )
    ap.add_argument(
        "--save-every", type=int, default=10, help="Save JSON every N completed chunks."
    )
    ap.add_argument(
        "--no-continue",
        action="store_true",
        help="Start fresh: ignore any existing output file instead of resuming.",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point: wires together argument parsing, logging, chunking,
    backend selection, and the translation loop. Returns a process exit
    code (0 success, 1 usage/setup error, 2 completed with some chunk
    failures).
    """
    args = parse_args(argv)

    # Hard memory constraint from the spec: never exceed 4 worker threads
    # regardless of what's requested on the CLI.
    workers = max(1, min(args.workers, 4))

    log_file = args.output.with_suffix(".log")
    configure_logging(log_file)

    signal.signal(signal.SIGINT, _handle_sigint)

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as e:
        logger.error(f"Could not read input file {args.input}: {e}")
        return 1

    chunks = chunk_text(text, args.chunk_size)
    if not chunks:
        logger.error("Input file produced zero chunks after splitting (empty file?)")
        return 1
    logger.info(
        f"Split input into {len(chunks)} chunk(s) of up to {args.chunk_size} chars"
    )

    existing: dict[str, str] = (
        {} if args.no_continue else load_existing_results(args.output)
    )
    if existing:
        logger.info(
            f"Resuming: {len(existing)} chunk(s) already translated in {args.output}"
        )

    try:
        backend_name, translate_fn = select_backend(
            args.backend, args.source, args.target
        )
    except (UnknownBackendError, NoBackendAvailableError) as e:
        logger.error(str(e))
        return 1
    logger.info(f"Using backend: {backend_name} ({args.source} -> {args.target})")

    results = run_translation(
        chunks=chunks,
        existing=existing,
        translate_fn=translate_fn,
        source_lang=args.source,
        target_lang=args.target,
        output_path=args.output,
        failed_path=args.failed,
        workers=workers,
        delay=args.delay,
        save_every=args.save_every,
    )

    failed_count = len(chunks) - len(results)
    if failed_count > 0:
        logger.warning(f"{failed_count} chunk(s) failed; see {args.failed}")
        return 2

    logger.info("All chunks translated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
