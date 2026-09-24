#!/data/data/com.termux/files/home/.local/bin/python
"""Translate one-word-per-line files on Termux Android 7 ARMv8l.

This script targets Python 3.12 on 32-bit ARM Termux with limited memory. It uses
only the standard library, loguru, and the selected backend package.

Supported backends:
- deepl
- deep_translator
- libretranslate_remote
- translate
- translators_bing
- googletrans
- pygoogletranslation
- boto3
- baidu
- alibaba
- watson
- azure

The implementation deliberately excludes native machine-learning runtimes,
local model-serving stacks, and cloud SDKs that require native extensions or
large compiled dependency trees unsuitable for this platform. No offline model
is loaded; offline-style operation requires a LibreTranslate server elsewhere
on the LAN or Internet.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

try:
    from loguru import logger
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: install it with 'pip install loguru'"
    ) from exc


class BackendError(Exception):
    """Raised when a translation backend cannot translate a word."""


TranslatorCallable = Callable[[str], str]
Factory = Callable[[str, str, str], TranslatorCallable]


_LANG_MAP: dict[str, dict[str, str]] = {
    "deepl": {
        "fr": "FR",
        "en": "EN-US",
        "de": "DE",
        "es": "ES",
        "it": "IT",
        "pt": "PT-PT",
        "nl": "NL",
        "pl": "PL",
        "ru": "RU",
        "ja": "JA",
        "zh": "ZH",
    },
    "deep_translator": {
        "fr": "fr",
        "en": "en",
        "de": "de",
        "es": "es",
        "it": "it",
        "pt": "pt",
        "nl": "nl",
        "pl": "pl",
        "ru": "ru",
        "ja": "ja",
        "zh": "zh-CN",
    },
    "libretranslate_remote": {
        "fr": "fr",
        "en": "en",
        "de": "de",
        "es": "es",
        "it": "it",
        "pt": "pt",
        "nl": "nl",
        "pl": "pl",
        "ru": "ru",
        "ja": "ja",
        "zh": "zh",
    },
    "boto3": {
        "fr": "fr",
        "en": "en",
        "de": "de",
        "es": "es",
        "it": "it",
        "pt": "pt",
        "zh": "zh",
    },
    "baidu": {
        "fr": "fra",
        "en": "en",
        "de": "de",
        "es": "spa",
        "it": "it",
        "pt": "pt",
        "zh": "zh",
    },
    "azure": {
        "fr": "fr",
        "en": "en",
        "de": "de",
        "es": "es",
        "it": "it",
        "pt": "pt",
        "zh": "zh-Hans",
    },
}

_SERIAL_LOCKS: dict[str, threading.Lock] = {
    "googletrans": threading.Lock(),
    "pygoogletranslation": threading.Lock(),
    "translators_bing": threading.Lock(),
}

_CONSOLE_LOCK = threading.Lock()
_RESULTS_LOCK = threading.Lock()
_FAILED_LOCK = threading.Lock()
_PROGRESS_LOCK = threading.Lock()


def _configure_logging() -> None:
    """Configure compact stderr logging and a rotating UTF-8 file log."""
    logger.remove()
    logger.add(
        "translate_words.log",
        level="DEBUG",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {thread.name} | {message}",
    )
    logger.add(
        sys.stderr,
        level="ERROR",
        format="<red>{level}</red>: {message}",
    )


def _print(message: str) -> None:
    """Print one complete console message without interleaving output."""
    with _CONSOLE_LOCK:
        print(message, flush=True)


def _language(backend: str, code: str) -> str:
    """Return a backend-specific language code, warning for unknown codes."""
    mapped = _LANG_MAP.get(backend, {}).get(code.casefold())
    if mapped is None:
        logger.warning(
            "No language mapping for backend '{}' and code '{}'; using raw code",
            backend,
            code,
        )
        return code
    return mapped


def _require_python_and_platform() -> None:
    """Validate the requested Python version and the Termux ARM target."""
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(
            f"Python 3.12 is required; detected {platform.python_version()}"
        )
    machine = platform.machine().casefold()
    if machine not in {"armv8l", "armv7l", "armv7"}:
        raise SystemExit(
            f"This script targets 32-bit ARM Termux; detected architecture '{machine}'"
        )
    if sys.maxsize > 2**32:
        raise SystemExit("This script requires a 32-bit Python process")


def _import(name: str):
    """Import a backend module only after the user selects that backend."""
    try:
        return importlib.import_module(name)
    except Exception as exc:
        raise BackendError(f"cannot import {name}: {exc}") from exc


def _make_deepl(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh DeepL client for each translation request."""
    key = os.getenv("DEEPL_API_KEY")
    if not key:
        raise BackendError("DEEPL_API_KEY is not set")
    _import("deepl")
    source_code = _language("deepl", source)
    target_code = _language("deepl", target)

    def translate(text: str) -> str:
        """Translate one text through a fresh DeepL client."""
        try:
            module = importlib.import_module("deepl")
            client = module.DeepLClient(key)
            return str(
                client.translate_text(
                    text,
                    source_lang=source_code,
                    target_lang=target_code,
                )
            )
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_deep_translator(
    source: str, target: str, script_path: str
) -> TranslatorCallable:
    """Create a fresh deep-translator Google client for each request."""
    _import("deep_translator")
    source_code = _language("deep_translator", source)
    target_code = _language("deep_translator", target)

    def translate(text: str) -> str:
        """Translate one text using the Google wrapper."""
        try:
            module = importlib.import_module("deep_translator")
            client = module.GoogleTranslator(
                source=source_code,
                target=target_code,
            )
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_libretranslate_remote(
    source: str, target: str, script_path: str
) -> TranslatorCallable:
    """Create a remote LibreTranslate client from LIBRETRANSLATE_URL."""
    url = os.getenv("LIBRETRANSLATE_URL")
    if not url:
        raise BackendError("LIBRETRANSLATE_URL is not set")
    _import("deep_translator")
    source_code = _language("libretranslate_remote", source)
    target_code = _language("libretranslate_remote", target)

    def translate(text: str) -> str:
        """Translate one text through a remote LibreTranslate server."""
        try:
            module = importlib.import_module("deep_translator")
            client = module.LibreTranslateTranslator(
                source=source_code,
                target=target_code,
                api_url=url.rstrip("/"),
            )
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_translate(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh translate-package client for each request."""
    if Path(script_path).stem.casefold() == "translate":
        raise BackendError(
            "the local script name resolves to the translate package; rename it"
        )
    _import("translate")

    def translate(text: str) -> str:
        """Translate one text using the translate package."""
        try:
            module = importlib.import_module("translate")
            client = module.Translator(from_lang=source, to_lang=target)
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_translators_bing(
    source: str, target: str, script_path: str
) -> TranslatorCallable:
    """Create a serialized translators Bing wrapper."""
    _import("translators")
    lock = _SERIAL_LOCKS["translators_bing"]
    logger.warning(
        "translators_bing is serialized because each request may start a JS runtime"
    )

    def translate(text: str) -> str:
        """Translate one text through the serialized Bing scraper."""
        try:
            module = importlib.import_module("translators")
            with lock:
                return str(
                    module.translate_text(
                        query=text,
                        translator="bing",
                        from_language=source,
                        to_language=target,
                    )
                )
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_googletrans(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create one serialized googletrans client."""
    module = _import("googletrans")
    client = module.Translator()
    lock = _SERIAL_LOCKS["googletrans"]

    def translate(text: str) -> str:
        """Translate one text through the serialized Google client."""
        try:
            with lock:
                result = client.translate(text, src=source, dest=target)
                return str(result.text)
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_pygoogletranslation(
    source: str, target: str, script_path: str
) -> TranslatorCallable:
    """Create one serialized pygoogletranslation client."""
    module = _import("pygoogletranslation")
    client_class = getattr(module, "Translator", None)
    if client_class is None:
        raise BackendError("pygoogletranslation.Translator is unavailable")
    client = client_class()
    lock = _SERIAL_LOCKS["pygoogletranslation"]

    def translate(text: str) -> str:
        """Translate one text through the serialized translation client."""
        try:
            with lock:
                result = client.translate(text, src=source, dest=target)
                return str(getattr(result, "text", result))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_boto3(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh AWS Translate client for each request."""
    _import("boto3")
    source_code = _language("boto3", source)
    target_code = _language("boto3", target)

    def translate(text: str) -> str:
        """Translate one text through AWS Translate."""
        try:
            module = importlib.import_module("boto3")
            client = module.client("translate")
            response = client.translate_text(
                Text=text,
                SourceLanguageCode=source_code,
                TargetLanguageCode=target_code,
            )
            return str(response["TranslatedText"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_baidu(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh Baidu AIP client for each request."""
    app_id = os.getenv("BAIDU_APP_ID")
    api_key = os.getenv("BAIDU_API_KEY")
    secret_key = os.getenv("BAIDU_SECRET_KEY")
    if not all((app_id, api_key, secret_key)):
        raise BackendError(
            "BAIDU_APP_ID, BAIDU_API_KEY, and BAIDU_SECRET_KEY are required"
        )
    _import("aip")
    source_code = _language("baidu", source)
    target_code = _language("baidu", target)

    def translate(text: str) -> str:
        """Translate one text through Baidu translation."""
        try:
            module = importlib.import_module("aip")
            client = module.AipNlp(app_id, api_key, secret_key)
            response = client.translate(text, fromLang=source_code, toLang=target_code)
            if "trans_result" not in response:
                raise BackendError(str(response))
            return str(response["trans_result"]["dst"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_alibaba(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create an Alibaba machine-translation request factory."""
    access_key = os.getenv("ALIBABA_ACCESS_KEY_ID")
    secret = os.getenv("ALIBABA_ACCESS_KEY_SECRET")
    region = os.getenv("ALIBABA_REGION", "cn-hangzhou")
    if not access_key or not secret:
        raise BackendError(
            "ALIBABA_ACCESS_KEY_ID and ALIBABA_ACCESS_KEY_SECRET are required"
        )
    _import("aliyunsdkcore")
    _import("aliyunsdkalimt")
    source_code = _language("alibaba", source)
    target_code = _language("alibaba", target)

    def translate(text: str) -> str:
        """Translate one text through Alibaba Cloud machine translation."""
        try:
            core = importlib.import_module("aliyunsdkcore.client")
            request_module = importlib.import_module("aliyunsdkalimt.request.v20181012")
            client = core.AcsClient(access_key, secret, region)
            request = request_module.TranslateGeneralRequest()
            request.set_SourceLanguage(source_code)
            request.set_TargetLanguage(target_code)
            request.set_SourceText(text)
            response = client.do_action_with_exception(request)
            payload = json.loads(response)
            return str(payload["Data"]["Translated"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_watson(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh IBM Watson client for each request."""
    api_key = os.getenv("WATSON_API_KEY")
    url = os.getenv("WATSON_URL")
    if not api_key or not url:
        raise BackendError("WATSON_API_KEY and WATSON_URL are required")
    _import("ibm_watson")

    def translate(text: str) -> str:
        """Translate one text through IBM Watson Language Translator."""
        try:
            module = importlib.import_module("ibm_watson")
            authenticator_module = importlib.import_module(
                "ibm_cloud_sdk_core.authenticators"
            )
            authenticator = authenticator_module.IamAuthenticator(api_key)
            client = module.LanguageTranslatorV3(
                version="2018-05-01",
                authenticator=authenticator,
            )
            client.set_service_url(url)
            response = client.translate(
                text=[text],
                source=source,
                target=target,
            ).get_result()
            return str(response["translations"][0]["translation"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_azure(source: str, target: str, script_path: str) -> TranslatorCallable:
    """Create a fresh Azure Translator request client for each request."""
    key = os.getenv("AZURE_TRANSLATOR_KEY")
    region = os.getenv("AZURE_TRANSLATOR_REGION")
    endpoint = os.getenv(
        "AZURE_TRANSLATOR_ENDPOINT",
        "https://api.cognitive.microsofttranslator.com",
    )
    if not key or not region:
        raise BackendError(
            "AZURE_TRANSLATOR_KEY and AZURE_TRANSLATOR_REGION are required"
        )
    _import("requests")
    source_code = _language("azure", source)
    target_code = _language("azure", target)

    def translate(text: str) -> str:
        """Translate one text through Azure Translator."""
        try:
            requests = importlib.import_module("requests")
            response = requests.post(
                f"{endpoint.rstrip('/')}/translate",
                params={"api-version": "3.0", "from": source_code, "to": target_code},
                headers={
                    "Ocp-Apim-Subscription-Key": key,
                    "Ocp-Apim-Subscription-Region": region,
                    "Content-Type": "application/json",
                },
                json=[{"Text": text}],
                timeout=30,
            )
            response.raise_for_status()
            return str(response.json()[0]["translations"][0]["text"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


_BACKEND_FACTORIES: dict[str, Factory] = {
    "deepl": _make_deepl,
    "deep_translator": _make_deep_translator,
    "libretranslate_remote": _make_libretranslate_remote,
    "translate": _make_translate,
    "translators_bing": _make_translators_bing,
    "googletrans": _make_googletrans,
    "pygoogletranslation": _make_pygoogletranslation,
    "boto3": _make_boto3,
    "baidu": _make_baidu,
    "alibaba": _make_alibaba,
    "watson": _make_watson,
    "azure": _make_azure,
}


def _fallback_order() -> list[str]:
    """Return the configured default backend fallback order."""
    order: list[str] = []
    if os.getenv("DEEPL_API_KEY"):
        order.append("deepl")
    order.append("deep_translator")
    if os.getenv("LIBRETRANSLATE_URL"):
        order.append("libretranslate_remote")
    order.extend(
        [
            "translate",
            "translators_bing",
            "googletrans",
            "pygoogletranslation",
        ]
    )
    return order


def _select_backend(
    preferred: str | None,
    source: str,
    target: str,
    script_path: str,
) -> tuple[str, TranslatorCallable]:
    """Initialize the preferred backend or the first usable fallback."""
    candidates = [preferred] if preferred else _fallback_order()
    failures: list[str] = []

    for name in candidates:
        if name not in _BACKEND_FACTORIES:
            raise SystemExit(
                f"Unknown backend '{name}'. Choose from: "
                + ", ".join(sorted(_BACKEND_FACTORIES))
            )
        try:
            translator = _BACKEND_FACTORIES[name](source, target, script_path)
            if failures:
                _print(
                    f"⚠️  Backend '{failures[-1]}' unavailable — "
                    f"falling back to '{name}'."
                )
            logger.debug("Selected backend '{}'", name)
            return name, translator
        except Exception as exc:
            failures.append(name)
            logger.warning("Backend '{}' unavailable: {}", name, exc)
            if preferred:
                raise SystemExit(
                    f"Backend '{name}' is unavailable: {exc}. "
                    "Install its package and configure its environment variables."
                ) from exc

    raise SystemExit(
        "No usable backend was found. Install deep_translator or configure "
        "one of the supported backends."
    )


def _read_words(path: Path) -> list[str]:
    """Read non-empty words while preserving their input order."""
    if not path.is_file():
        raise SystemExit(f"Input file does not exist: {path}")
    words: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                word = line.strip()
                if word:
                    words.append(word)
    except OSError as exc:
        raise SystemExit(f"Cannot read input file '{path}': {exc}") from exc
    return words


def _load_results(path: Path, continue_run: bool) -> dict[str, str]:
    """Load a previous JSON mapping when resume mode is enabled."""
    if not continue_run or not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object")
        return {str(key): str(value) for key, value in data.items()}
    except Exception as exc:
        raise SystemExit(f"Cannot load existing output '{path}': {exc}") from exc


def _atomic_save(path: Path, results: dict[str, str]) -> None:
    """Write JSON through a temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _append_failed(path: Path, word: str) -> None:
    """Append one permanently failed word to the failure file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _FAILED_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{word}\n")


def _translate_one(
    word: str,
    translator: TranslatorCallable,
    delay: float,
    failed_path: Path,
) -> tuple[str, str | None]:
    """Translate one word with three attempts and exponential backoff."""
    for attempt in range(1, 4):
        try:
            time.sleep(delay)
            translated = str(translator(word)).strip()
            if not translated or translated.casefold() == word.casefold():
                raise BackendError("empty or identity translation")
            return word, translated
        except Exception as exc:
            logger.warning(
                "Attempt {}/3 failed for word {!r}: {}",
                attempt,
                word,
                exc,
            )
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    _append_failed(failed_path, word)
    logger.error("Giving up on word {!r}; appended to {}", word, failed_path)
    return word, None


def _parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Translate a one-word-per-line file into a JSON mapping."
    )
    parser.add_argument("-i", "--input", default="words.txt")
    parser.add_argument("-o", "--output", default="words.json")
    parser.add_argument("--failed", default="failed.txt")
    parser.add_argument("-s", "--source", default="fr")
    parser.add_argument("-t", "--target", default="en")
    parser.add_argument("-b", "--backend")
    parser.add_argument("-w", "--workers", type=int, default=2)
    parser.add_argument("-d", "--delay", type=float, default=0.5)
    parser.add_argument("--save-every", type=int, default=50)
    parser.add_argument("--no-continue", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.save_every < 1:
        parser.error("--save-every must be at least 1")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    return args


def _run(args: argparse.Namespace) -> int:
    """Run translation, periodic saves, resume handling, and interruption recovery."""
    input_path = Path(args.input)
    output_path = Path(args.output)
    failed_path = Path(args.failed)
    words = _read_words(input_path)
    results = _load_results(output_path, not args.no_continue)

    if not args.no_continue:
        _print(f"Loaded {len(results)} existing translations from {output_path}")

    pending = [word for word in words if word not in results]
    total = len(words)
    completed = total - len(pending)
    _print(f"Processing {len(pending)} pending words out of {total}")

    if not pending:
        _atomic_save(output_path, results)
        return 0

    backend_name, translator = _select_backend(
        args.backend,
        args.source,
        args.target,
        str(Path(__file__).resolve()),
    )
    _print(f"Using backend: {backend_name}")

    executor = ThreadPoolExecutor(max_workers=min(args.workers, 2))
    futures: dict[Future[tuple[str, str | None]], str] = {}

    try:
        for word in pending:
            future = executor.submit(
                _translate_one,
                word,
                translator,
                args.delay,
                failed_path,
            )
            futures[future] = word

        for future in as_completed(futures):
            word, translated = future.result()
            completed += 1
            if translated is not None:
                with _RESULTS_LOCK:
                    results[word] = translated
                _print(f"[{completed}/{total}] ✓ {word} -> {translated}")
            else:
                _print(f"[{completed}/{total}] ✗ {word} (failed → {failed_path})")

            with _PROGRESS_LOCK:
                if completed % args.save_every == 0:
                    with _RESULTS_LOCK:
                        snapshot = dict(results)
                    _atomic_save(output_path, snapshot)
                    _print(f"Saved {len(snapshot)} translations to {output_path}")

        with _RESULTS_LOCK:
            _atomic_save(output_path, dict(results))
        _print(f"Completed. Saved {len(results)} translations to {output_path}")
        return 0
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        with _RESULTS_LOCK:
            _atomic_save(output_path, dict(results))
        _print(f"Interrupted. Current state saved to {output_path}")
        return 130
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def main() -> int:
    """Configure the process and execute the command-line workflow."""
    _require_python_and_platform()
    _configure_logging()
    args = _parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
