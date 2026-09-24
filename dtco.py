#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate a text file in independent character-limited chunks.

The script is designed for Termux and uses only lightweight, optional
translation libraries.  Translation libraries are imported lazily, so only
the selected backend must be installed.

Example:

    pip install loguru deep_translator

    python translate_chunks.py \
        --input input.txt \
        --output chunks.json \
        --source en \
        --target fr

The output JSON has this form:

    {
        "0": "Translated first chunk",
        "1": "Translated second chunk"
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from loguru import logger


# A translator callable accepts one source-language string and returns the
# translated string.
Translator = Callable[[str], str]


# The requested fallback order.  DeepL is considered only when its API key is
# available because the DeepL client cannot work without one.
FALLBACK_BACKENDS = (
    "deepl",
    "deep_translator",
    "translate",
    "translators_bing",
    "googletrans",
    "pygoogletranslation",
)


# These aliases make common language names usable while preserving the user's
# language-code interface.
LANGUAGE_ALIASES: dict[str, str] = {
    "auto": "auto",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "zh": "zh-CN",
    "zh-tw": "zh-TW",
    "zh_tw": "zh-TW",
    "he": "iw",
    "jv": "jw",
    "pt-br": "pt",
    "pt_br": "pt",
}


class TranslationError(RuntimeError):
    """Raised when a chunk cannot be translated."""


class RequestLimiter:
    """
    Process-wide request limiter.

    A single limiter is shared by all worker threads, ensuring that the
    configured delay applies between requests globally rather than separately
    inside each worker.
    """

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next_request_time = 0.0

    def wait(self) -> None:
        """Wait until the next request is allowed to start."""
        with self._lock:
            now = time.monotonic()
            wait_for = self._next_request_time - now

            if wait_for > 0:
                time.sleep(wait_for)

            # Reserve the next request slot while still holding the lock.
            self._next_request_time = time.monotonic() + self.delay


class SerializedTranslator:
    """
    Wrap a translator so only one call can use it at a time.

    googletrans and pygoogletranslation can use shared internal state or
    sessions that are not reliably thread-safe.  Serializing those calls
    avoids concurrent access to one client.
    """

    def __init__(self, translator: Translator) -> None:
        self._translator = translator
        self._lock = threading.Lock()

    def __call__(self, text: str) -> str:
        with self._lock:
            return self._translator(text)


def normalize_language(language: str) -> str:
    """Normalize a language code without changing unknown codes."""
    cleaned = language.strip()
    return LANGUAGE_ALIASES.get(cleaned.lower(), cleaned)


def _deep_translator_language(language: str) -> str:
    """
    Return a language code accepted by deep_translator.

    deep_translator accepts normal two-letter codes for most languages and
    uses a few special values for Chinese variants.
    """
    code = normalize_language(language)
    return {
        "zh-CN": "zh-CN",
        "zh-TW": "zh-TW",
    }.get(code, code)


def _deepl_language(language: str) -> str:
    """Return a DeepL target-language code."""
    code = normalize_language(language).upper()

    # DeepL uses these language names/codes for common variants.
    return {
        "EN": "EN-US",
        "PT": "PT-PT",
        "ZH-CN": "ZH-HANS",
        "ZH-TW": "ZH-HANT",
    }.get(code, code)


def _google_language(language: str) -> str:
    """Return a Google-style language code."""
    return normalize_language(language).lower().replace("_", "-")


def _make_deep_translator(source: str, target: str) -> Translator:
    """
    Create a deep_translator callable.

    A new GoogleTranslator object is created for every request.  This keeps
    worker interactions independent and avoids sharing mutable client state.
    """
    from deep_translator import GoogleTranslator

    source_code = _deep_translator_language(source)
    target_code = _deep_translator_language(target)

    def translate(text: str) -> str:
        client = GoogleTranslator(source=source_code, target=target_code)
        return str(client.translate(text))

    return translate


def _make_deepl(source: str, target: str) -> Translator:
    """Create a DeepL API callable using DEEPL_API_KEY."""
    import deepl

    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPL_API_KEY is not set")

    client = deepl.DeepLClient(api_key)
    target_code = _deepl_language(target)

    def translate(text: str) -> str:
        # DeepL's Python API does not require the source language for ordinary
        # text translation; source is retained here for factory consistency.
        del source
        result = client.translate_text(text, target_lang=target_code)
        return str(result.text if hasattr(result, "text") else result)

    return translate


def _make_translate(source: str, target: str) -> Translator:
    """Create a callable for the lightweight ``translate`` package."""
    from translate import Translator as TranslateClient

    source_code = normalize_language(source)
    target_code = normalize_language(target)

    def translate_text(text: str) -> str:
        # A fresh client per call avoids sharing sessions between workers.
        client = TranslateClient(
            from_lang=source_code,
            to_lang=target_code,
        )
        return str(client.translate(text))

    return translate_text


def _make_translators_bing(source: str, target: str) -> Translator:
    """
    Create a callable for the ``translators`` package's Bing backend.

    The package may require Node.js for its Bing implementation, as noted in
    the command-line documentation.
    """
    import translators

    source_code = _google_language(source)
    target_code = _google_language(target)

    def translate_text(text: str) -> str:
        result = translators.translate_text(
            query=text,
            translator="bing",
            from_language=source_code,
            to_language=target_code,
        )
        return str(result)

    return translate_text


def _make_googletrans(source: str, target: str) -> Translator:
    """Create a serialized callable for googletrans."""
    from googletrans import Translator as GoogleTransClient

    source_code = _google_language(source)
    target_code = _google_language(target)

    def translate_text(text: str) -> str:
        # A fresh client per call avoids stale or cross-thread sessions.
        client = GoogleTransClient()
        result = client.translate(text, src=source_code, dest=target_code)
        return str(result.text)

    return SerializedTranslator(translate_text)


def _make_pygoogletranslation(source: str, target: str) -> Translator:
    """
    Create a serialized callable for pygoogletranslation.

    The package has exposed Translator classes with this API in its commonly
    used releases.
    """
    from pygoogletranslation import Translator as PyGoogleTranslator

    source_code = _google_language(source)
    target_code = _google_language(target)

    def translate_text(text: str) -> str:
        client = PyGoogleTranslator()
        result = client.translate(text, src=source_code, dest=target_code)

        # Some versions return a string; others return an object with ``text``.
        return str(getattr(result, "text", result))

    return SerializedTranslator(translate_text)


BACKEND_FACTORIES: dict[str, Callable[[str, str], Translator]] = {
    "deep_translator": _make_deep_translator,
    "deepl": _make_deepl,
    "translate": _make_translate,
    "translators_bing": _make_translators_bing,
    "googletrans": _make_googletrans,
    "pygoogletranslation": _make_pygoogletranslation,
}


def configure_logging() -> None:
    """Configure DEBUG logging in a file and ERROR logging on stderr."""
    logger.remove()

    logger.add(
        "translate_chunks.log",
        level="DEBUG",
        rotation="5 MB",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    logger.add(
        sys.stderr,
        level="ERROR",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


def split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """
    Split text into chunks no longer than ``chunk_size`` where possible.

    The function scans backward from the limit for whitespace so it does not
    split a word unnecessarily.  If a single word is longer than the limit,
    a hard split is used to guarantee progress and bounded chunk size.
    """
    if chunk_size <= 0:
        raise ValueError("chunk size must be greater than zero")

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= chunk_size:
            candidate = remaining
            remaining = ""
        else:
            boundary = remaining.rfind(None if False else " ", 0, chunk_size + 1)

            # Also consider tabs and newlines as word boundaries.
            whitespace_boundary = max(
                boundary,
                remaining.rfind("\t", 0, chunk_size + 1),
                remaining.rfind("\n", 0, chunk_size + 1),
                remaining.rfind("\r", 0, chunk_size + 1),
            )

            if whitespace_boundary > 0:
                candidate = remaining[:whitespace_boundary]
                remaining = remaining[whitespace_boundary:]
            else:
                # No boundary was found.  This is normally a very long word.
                candidate = remaining[:chunk_size]
                remaining = remaining[chunk_size:]

        candidate = candidate.strip()
        if candidate:
            chunks.append(candidate)

        # Discard whitespace between chunks.  Leading and trailing whitespace
        # is intentionally not part of translated chunks.
        remaining = remaining.lstrip()

    return chunks


def load_existing_output(path: Path, continue_run: bool) -> dict[str, str]:
    """Load an existing JSON result, or return an empty result dictionary."""
    if not continue_run or not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read existing output {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"existing output {path} must contain a JSON object")

    # Keep only string keys and values.  This prevents malformed resume files
    # from causing unexpected output.
    return {
        str(index): str(value)
        for index, value in data.items()
        if isinstance(value, str)
    }


def atomic_save(path: Path, translations: dict[str, str]) -> None:
    """
    Atomically save translations as UTF-8 JSON.

    The temporary file is placed in the destination directory so os.replace()
    remains atomic on the same filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_name: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(
                translations,
                temporary,
                ensure_ascii=False,
                indent=2,
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())

        os.replace(temporary_name, path)
        temporary_name = None
        logger.debug("Saved {} translated chunks to {}", len(translations), path)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def append_failed(path: Path, chunk_index: int) -> None:
    """Append a failed chunk index to the configured failure file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(f"{chunk_index}\n")


def is_identity_translation(source: str, translated: str) -> bool:
    """
    Detect an obviously untranslated result.

    Comparison is case-insensitive and ignores surrounding whitespace.  This
    intentionally errs on the side of retrying because a translation service
    returning the original text may indicate a failed request.
    """
    return source.strip().casefold() == translated.strip().casefold()


def choose_backend(requested: str | None) -> str:
    """
    Select an explicitly requested backend or the first available fallback.

    Availability is checked by importing the corresponding package.  A
    backend-specific API-key check is performed for DeepL.
    """
    if requested:
        if requested == "auto":
            requested = None
        else:
            if requested not in BACKEND_FACTORIES:
                valid = ", ".join(sorted(BACKEND_FACTORIES))
                raise RuntimeError(
                    f"unsupported backend {requested!r}; choose one of: {valid}"
                )

            if requested == "deepl" and not os.environ.get("DEEPL_API_KEY"):
                raise RuntimeError(
                    "backend 'deepl' requires the DEEPL_API_KEY environment variable"
                )

            return requested

    for backend in FALLBACK_BACKENDS:
        if backend == "deepl" and not os.environ.get("DEEPL_API_KEY"):
            continue

        try:
            if backend == "deep_translator":
                import deep_translator  # noqa: F401
            elif backend == "deepl":
                import deepl  # noqa: F401
            elif backend == "translate":
                import translate  # noqa: F401
            elif backend == "translators_bing":
                import translators  # noqa: F401
            elif backend == "googletrans":
                import googletrans  # noqa: F401
            elif backend == "pygoogletranslation":
                import pygoogletranslation  # noqa: F401
        except ImportError:
            logger.debug("Backend {} is unavailable", backend)
            continue

        return backend

    packages = ", ".join(FALLBACK_BACKENDS)
    raise RuntimeError(
        f"no translation backend is installed; install one of: {packages}"
    )


def translate_one(
    index: int,
    text: str,
    translator: Translator,
    limiter: RequestLimiter,
    attempts: int = 3,
) -> tuple[int, str]:
    """
    Translate one chunk with retries and exponential backoff.

    The request limiter is used before every attempt, including retries.
    """
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            limiter.wait()
            translated = str(translator(text)).strip()

            if not translated:
                raise TranslationError("backend returned an empty translation")

            if is_identity_translation(text, translated):
                raise TranslationError("backend returned the source text unchanged")

            logger.debug(
                "Chunk {} translated successfully on attempt {}",
                index,
                attempt,
            )
            return index, translated

        except Exception as exc:  # Backends expose different exception types.
            last_error = exc
            logger.debug(
                "Chunk {} attempt {}/{} failed: {}",
                index,
                attempt,
                attempts,
                exc,
            )

            if attempt < attempts:
                # 1, 2, 4 seconds between failed attempts.
                time.sleep(2 ** (attempt - 1))

    raise TranslationError(
        f"chunk {index} failed after {attempts} attempts: {last_error}"
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Translate a text file in resumable chunks."
    )

    parser.add_argument(
        "-i",
        "--input",
        default="input.txt",
        help="Input text file. Default: input.txt",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="chunks.json",
        help="Output JSON file. Default: chunks.json",
    )
    parser.add_argument(
        "--failed",
        default="failed.txt",
        help="Failed chunk-index file. Default: failed.txt",
    )
    parser.add_argument(
        "-s",
        "--source",
        default="en",
        help="Source language code. Default: en",
    )
    parser.add_argument(
        "-t",
        "--target",
        default="fr",
        help="Target language code. Default: fr",
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=["auto", *BACKEND_FACTORIES.keys()],
        default="auto",
        help="Translation backend. Default: automatic fallback order.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=2,
        help="Concurrent worker threads, maximum 2. Default: 2",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between requests globally. Default: 0.5",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2500,
        help="Maximum chunk length in characters. Default: 2500",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=10,
        help="Save after this many completed chunks. Default: 10",
    )
    parser.add_argument(
        "--no-continue",
        action="store_true",
        help="Ignore an existing output file and start from scratch.",
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Validate resource and size limits before starting work."""
    if not 1 <= args.workers <= 2:
        raise ValueError("--workers must be between 1 and 2")

    if args.delay < 0:
        raise ValueError("--delay cannot be negative")

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be greater than zero")

    if args.save_every <= 0:
        raise ValueError("--save-every must be greater than zero")


def read_input(path: Path) -> str:
    """Read the complete input file as UTF-8 text."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read input file {path}: {exc}") from exc


def run(args: argparse.Namespace) -> int:
    """Run the translation pipeline."""
    validate_args(args)

    input_path = Path(args.input)
    output_path = Path(args.output)
    failed_path = Path(args.failed)

    source_text = read_input(input_path)
    chunks = split_into_chunks(source_text, args.chunk_size)

    translations = load_existing_output(
        output_path,
        continue_run=not args.no_continue,
    )

    # Remove out-of-range entries when starting with an accidentally mismatched
    # output file.  Valid existing chunks are retained for resume.
    translations = {
        index: value
        for index, value in translations.items()
        if index.isdigit() and int(index) < len(chunks)
    }

    pending = [
        (index, chunk)
        for index, chunk in enumerate(chunks)
        if str(index) not in translations
    ]

    logger.debug(
        "Input produced {} chunks; {} already translated; {} pending",
        len(chunks),
        len(translations),
        len(pending),
    )

    if not pending:
        atomic_save(output_path, translations)
        logger.debug("Nothing to translate")
        return 0

    backend = choose_backend(None if args.backend == "auto" else args.backend)
    logger.debug("Using backend {}", backend)

    # Constructing the callable can fail if a dependency is partially
    # installed, credentials are invalid, or a backend has incompatible APIs.
    translator = BACKEND_FACTORIES[backend](
        normalize_language(args.source),
        normalize_language(args.target),
    )
    limiter = RequestLimiter(args.delay)

    completed_since_save = 0

    with ThreadPoolExecutor(
        max_workers=args.workers,
        thread_name_prefix="translator",
    ) as executor:
        future_to_index: dict[Future[tuple[int, str]], int] = {
            executor.submit(
                translate_one,
                index,
                chunk,
                translator,
                limiter,
            ): index
            for index, chunk in pending
        }

        try:
            for future in as_completed(future_to_index):
                index = future_to_index[future]

                try:
                    completed_index, translated = future.result()
                    translations[str(completed_index)] = translated
                    completed_since_save += 1

                    logger.debug(
                        "Completed chunk {} ({}/{})",
                        completed_index,
                        len(translations),
                        len(chunks),
                    )

                    if completed_since_save >= args.save_every:
                        atomic_save(output_path, translations)
                        completed_since_save = 0

                except Exception as exc:
                    logger.error("Chunk {} failed: {}", index, exc)
                    append_failed(failed_path, index)

        except KeyboardInterrupt:
            logger.error("Interrupted; saving completed translations")
            for future in future_to_index:
                future.cancel()

            # shutdown(wait=False) is not used here because the context
            # manager performs a clean worker shutdown.  Completed results
            # already collected above are preserved.
            raise

    atomic_save(output_path, translations)

    failed_count = len(chunks) - len(translations)
    if failed_count:
        logger.error(
            "Finished with {} failed or incomplete chunks; see {}",
            failed_count,
            failed_path,
        )
        return 1

    logger.debug("All {} chunks translated successfully", len(chunks))
    return 0


def main() -> int:
    """Program entry point with clean error and Ctrl+C handling."""
    configure_logging()

    try:
        args = parse_args()
        return run(args)

    except KeyboardInterrupt:
        logger.error("Interrupted. Existing completed translations were saved.")
        return 130

    except Exception as exc:
        logger.error("Fatal error: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
