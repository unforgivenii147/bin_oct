#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate a one-word-per-line file into a JSON mapping on Termux.

Target platform
---------------
This script is designed for Termux on Android 7 running Python 3.12 on
32-bit ARM (armv8l). It uses only the Python standard library, loguru, and
the backend selected by the user.

Supported backends
------------------
Tier 1:
    deep_translator
    deepl

Tier 2:
    translate
    googletrans
    pygoogletranslation
    translators_bing

Tier 3:
    boto3
    baidu
    alibaba
    watson
    azure

Remote/offline alternative:
    libretranslate_remote

The remote LibreTranslate option does not run a translation engine locally.
It sends requests to a LibreTranslate server on another machine, such as a
PC, VPS, or Raspberry Pi on the LAN. Set LIBRETRANSLATE_URL, for example:

    export LIBRETRANSLATE_URL=http://192.168.1.50:5000

Excluded backends
-----------------
Local neural-machine-translation engines and cloud SDKs that require native
packages unavailable for this platform are deliberately not supported here.
This includes argostranslate, self-hosted libretranslate, opus_mt, nllb,
m2m100, transformers, torch, sentencepiece, ctranslate2, pydantic-core,
google-cloud-translate, yandex_cloud, openai, anthropic, and mistralai.

Those packages either require unavailable 32-bit ARM wheels, Rust/native
extensions that do not build reliably on Android 7, or heavyweight machine
learning dependencies. For offline use, run LibreTranslate on another
machine and use the pure-Python libretranslate_remote backend.

The program resumes from an existing JSON file by default, saves atomically,
retries failed requests, and can be interrupted safely with Ctrl+C.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from loguru import logger


class BackendError(RuntimeError):
    """Raised when a translation backend cannot be initialized or used."""


TranslationFunction = Callable[[str], str]


# These names are rejected before any import is attempted.
_FORBIDDEN_BACKENDS = {
    "argostranslate",
    "libretranslate",
    "opus_mt",
    "nllb",
    "m2m100",
    "transformers",
    "torch",
    "sentencepiece",
    "ctranslate2",
    "pydantic-core",
    "google-cloud-translate",
    "yandex_cloud",
    "openai",
    "anthropic",
    "mistralai",
}

# The default chain is intentionally limited to Termux-viable backends.
_DEFAULT_CHAIN = [
    "deepl",
    "deep_translator",
    "libretranslate_remote",
    "translate",
    "translators_bing",
    "googletrans",
    "pygoogletranslation",
]

_LANG_MAP = {
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
    "deep_translator": {},
    "translate": {},
    "googletrans": {},
    "pygoogletranslation": {},
    "translators_bing": {},
    "libretranslate_remote": {},
    "boto3": {},
    "baidu": {
        "fr": "fra",
        "en": "en",
        "de": "de",
        "es": "spa",
        "it": "it",
        "zh": "zh",
        "ja": "jp",
        "ru": "ru",
    },
    "alibaba": {},
    "watson": {},
    "azure": {},
}

# Separate locks are intentional: slow console output must not block file I/O.
_console_lock = threading.Lock()
_results_lock = threading.Lock()
_failed_lock = threading.Lock()
_counter_lock = threading.Lock()


def _configure_logging() -> None:
    """Configure the small rotating file log and compact error-only stderr log."""
    logger.remove()
    logger.add(
        "translate_words.log",
        level="DEBUG",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
        format=("{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {thread.name} | {message}"),
    )
    logger.add(
        sys.stderr,
        level="ERROR",
        format="<level>{level}: {message}</level>",
    )


def _mapped_language(backend: str, language: str) -> str:
    """Return a backend-specific language code, or the original code if unknown."""
    return _LANG_MAP.get(backend, {}).get(language.casefold(), language)


def _make_deep_translator(
    source: str, target: str, script_path: str
) -> TranslationFunction:
    """Create a per-request deep_translator GoogleTranslator wrapper."""
    del script_path
    try:
        from deep_translator import GoogleTranslator
    except Exception as exc:
        raise BackendError("install it with: pip install deep_translator") from exc

    mapped_source = _mapped_language("deep_translator", source)
    mapped_target = _mapped_language("deep_translator", target)

    def translate(text: str) -> str:
        """Translate one string with a fresh deep_translator client."""
        try:
            client = GoogleTranslator(
                source=mapped_source,
                target=mapped_target,
            )
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_deepl(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create a per-request DeepL API wrapper."""
    del script_path
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise BackendError("DEEPL_API_KEY is not set")

    try:
        import deepl
    except Exception as exc:
        raise BackendError("install it with: pip install deepl") from exc

    mapped_source = _mapped_language("deepl", source)
    mapped_target = _mapped_language("deepl", target)

    def translate(text: str) -> str:
        """Translate one string with a fresh DeepL client."""
        try:
            client = deepl.Translator(api_key)
            return str(
                client.translate_text(
                    text,
                    source_lang=mapped_source,
                    target_lang=mapped_target,
                )
            )
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_libretranslate_remote(
    source: str, target: str, script_path: str
) -> TranslationFunction:
    """Create a wrapper for a LibreTranslate server running on another machine."""
    del script_path
    api_url = os.environ.get("LIBRETRANSLATE_URL")
    if not api_url:
        raise BackendError("LIBRETRANSLATE_URL is not set")

    try:
        from deep_translator import LibreTranslateTranslator
    except Exception as exc:
        raise BackendError("install it with: pip install deep_translator") from exc

    def translate(text: str) -> str:
        """Translate one string through the configured LAN LibreTranslate server."""
        try:
            client = LibreTranslateTranslator(
                source=source,
                target=target,
                api_url=api_url.rstrip("/"),
            )
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_translate(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create a wrapper for either the upstream translate package or a fork."""
    try:
        module_path = Path(__import__("translate").__file__).resolve()
        if module_path == Path(script_path).resolve():
            raise BackendError(
                "import translate resolves to this script; rename this file"
            )
        import translate as translate_module
    except BackendError:
        raise
    except Exception as exc:
        raise BackendError("install it with: pip install translate") from exc

    translator_class = getattr(translate_module, "Translator", None)
    class_kwargs = {"from_lang": source, "to_lang": target}

    if translator_class is None:
        translator_class = getattr(translate_module, "GoogleTranslator", None)
        class_kwargs = {"source": source, "target": target}

    if translator_class is None:
        raise BackendError(
            "installed translate package has neither Translator nor GoogleTranslator"
        )

    def translate_text(text: str) -> str:
        """Translate one string with a fresh translate-package client."""
        try:
            client = translator_class(**class_kwargs)
            return str(client.translate(text))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate_text


def _make_googletrans(
    source: str, target: str, script_path: str
) -> TranslationFunction:
    """Create a serialized googletrans client wrapper."""
    del script_path
    try:
        from googletrans import Translator
    except Exception as exc:
        raise BackendError(
            'install it with: pip install "googletrans==4.0.0rc1"'
        ) from exc

    client = Translator()
    lock = threading.Lock()

    def translate(text: str) -> str:
        """Translate one string using one locked googletrans instance."""
        try:
            with lock:
                response = client.translate(text, src=source, dest=target)
                return str(response.text)
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_pygoogletranslation(
    source: str, target: str, script_path: str
) -> TranslationFunction:
    """Create a serialized pygoogletranslation client wrapper."""
    del script_path
    try:
        from pygoogletranslation import Translator
    except Exception as exc:
        raise BackendError("install it with: pip install pygoogletranslation") from exc

    client = Translator()
    lock = threading.Lock()

    def translate(text: str) -> str:
        """Translate one string using one locked pygoogletranslation instance."""
        try:
            with lock:
                response = client.translate(text, src=source, dest=target)
                return str(getattr(response, "text", response))
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_translators_bing(
    source: str, target: str, script_path: str
) -> TranslationFunction:
    """Create a serialized translators Bing wrapper using the Node.js runtime."""
    del script_path
    try:
        import translators
    except Exception as exc:
        raise BackendError(
            "install it with: pip install translators; pkg install nodejs"
        ) from exc

    logger.warning(
        "translators_bing uses a JavaScript subprocess per request; "
        "throughput will be low on Termux"
    )
    lock = threading.Lock()

    def translate(text: str) -> str:
        """Translate one string through the Bing translator scraper."""
        try:
            with lock:
                return str(
                    translators.translate_text(
                        query_text=text,
                        translator="bing",
                        from_language=source,
                        to_language=target,
                    )
                )
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_boto3(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create an AWS Translate wrapper using credentials from the environment."""
    del script_path
    try:
        import boto3
    except Exception as exc:
        raise BackendError("install it with: pip install boto3") from exc

    region = os.environ.get("AWS_REGION") or os.environ.get(
        "AWS_DEFAULT_REGION", "us-east-1"
    )
    mapped_source = _mapped_language("boto3", source)
    mapped_target = _mapped_language("boto3", target)

    def translate(text: str) -> str:
        """Translate one string with a fresh AWS client."""
        try:
            client = boto3.client("translate", region_name=region)
            response = client.translate_text(
                Text=text,
                SourceLanguageCode=mapped_source,
                TargetLanguageCode=mapped_target,
            )
            return str(response["TranslatedText"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_baidu(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create a Baidu AI translation wrapper."""
    del script_path
    app_id = os.environ.get("BAIDU_APP_ID")
    app_key = os.environ.get("BAIDU_APP_KEY")
    if not app_id or not app_key:
        raise BackendError("BAIDU_APP_ID and BAIDU_APP_KEY are required")

    try:
        from aip import AipNlp
    except Exception as exc:
        raise BackendError("install it with: pip install baidu-aip") from exc

    mapped_source = _mapped_language("baidu", source)
    mapped_target = _mapped_language("baidu", target)

    def translate(text: str) -> str:
        """Translate one string with a fresh Baidu client."""
        try:
            client = AipNlp(app_id, app_key, os.environ.get("BAIDU_SECRET_KEY", ""))
            response = client.translate(text, mapped_source, mapped_target)
            return str(response["data"]["trans_result"]["dst"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_alibaba(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create an Alibaba machine-translation wrapper."""
    del script_path
    access_key = os.environ.get("ALIBABA_ACCESS_KEY_ID")
    access_secret = os.environ.get("ALIBABA_ACCESS_KEY_SECRET")
    if not access_key or not access_secret:
        raise BackendError(
            "ALIBABA_ACCESS_KEY_ID and ALIBABA_ACCESS_KEY_SECRET are required"
        )

    try:
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkalimt.request.v20181012 import TranslateGeneralRequest
    except Exception as exc:
        raise BackendError(
            "install it with: pip install aliyun-python-sdk-alimt"
        ) from exc

    region = os.environ.get("ALIBABA_REGION", "cn-hangzhou")

    def translate(text: str) -> str:
        """Translate one string with a fresh Alibaba SDK client."""
        try:
            client = AcsClient(access_key, access_secret, region)
            request = TranslateGeneralRequest.TranslateGeneralRequest()
            request.set_SourceLanguage(source)
            request.set_TargetLanguage(target)
            request.set_Scene("general")
            request.set_FormatType("text")
            request.set_SourceText(text)
            response = json.loads(client.do_action_with_exception(request))
            return str(response["Data"]["Translated"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_watson(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create an IBM Watson Language Translator wrapper."""
    del script_path
    api_key = os.environ.get("WATSON_API_KEY")
    service_url = os.environ.get("WATSON_URL")
    if not api_key or not service_url:
        raise BackendError("WATSON_API_KEY and WATSON_URL are required")

    try:
        from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
        from ibm_watson import LanguageTranslatorV3
    except Exception as exc:
        raise BackendError("install it with: pip install ibm-watson") from exc

    def translate(text: str) -> str:
        """Translate one string with a fresh Watson client."""
        try:
            authenticator = IAMAuthenticator(api_key)
            client = LanguageTranslatorV3(
                version="2018-05-01",
                authenticator=authenticator,
            )
            client.set_service_url(service_url)
            response = client.translate(
                text=text,
                source=source,
                target=target,
            ).get_result()
            return str(response["translations"][0]["translation"])
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


def _make_azure(source: str, target: str, script_path: str) -> TranslationFunction:
    """Create an Azure Translator wrapper using key-based authentication."""
    del script_path
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    endpoint = os.environ.get(
        "AZURE_TRANSLATOR_ENDPOINT",
        "https://api.cognitive.microsofttranslator.com",
    )
    region = os.environ.get("AZURE_TRANSLATOR_REGION")
    if not key:
        raise BackendError("AZURE_TRANSLATOR_KEY is not set")

    try:
        from azure.ai.translation.text import TextTranslationClient
        from azure.core.credentials import AzureKeyCredential
    except Exception as exc:
        raise BackendError(
            "install it with: pip install azure-ai-translation-text"
        ) from exc

    def translate(text: str) -> str:
        """Translate one string with a fresh Azure client."""
        try:
            client = TextTranslationClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key),
            )
            kwargs = {"body": [{"text": text}], "to": [target]}
            if source:
                kwargs["from_parameter"] = source
            if region:
                kwargs["headers"] = {"Ocp-Apim-Subscription-Region": region}
            response = client.translate(**kwargs)
            return str(response[0].translations[0].text)
        except Exception as exc:
            raise BackendError(str(exc)) from exc

    return translate


_BACKEND_FACTORIES = {
    "deep_translator": _make_deep_translator,
    "deepl": _make_deepl,
    "libretranslate_remote": _make_libretranslate_remote,
    "translate": _make_translate,
    "googletrans": _make_googletrans,
    "pygoogletranslation": _make_pygoogletranslation,
    "translators_bing": _make_translators_bing,
    "boto3": _make_boto3,
    "baidu": _make_baidu,
    "alibaba": _make_alibaba,
    "watson": _make_watson,
    "azure": _make_azure,
}


def _backend_chain(preferred: str) -> List[str]:
    """Return the preferred backend followed by the remaining default choices."""
    if preferred == "default":
        return list(_DEFAULT_CHAIN)
    return [preferred] + [name for name in _DEFAULT_CHAIN if name != preferred]


def _select_backend(
    preferred: str, source: str, target: str, script_path: str
) -> Tuple[str, TranslationFunction]:
    """Initialize the first usable backend in the configured fallback chain."""
    if preferred in _FORBIDDEN_BACKENDS:
        raise BackendError(
            f"backend '{preferred}' is unavailable on Termux armv8l: "
            "it requires unsupported native, ML, Rust, or gRPC dependencies. "
            "Use deep_translator, deepl, or a LAN LibreTranslate server."
        )

    if preferred != "default" and preferred not in _BACKEND_FACTORIES:
        valid = ", ".join(sorted(_BACKEND_FACTORIES))
        raise BackendError(
            f"unknown backend '{preferred}'. Supported backends: {valid}"
        )

    last_error = "no backend was attempted"
    chain = _backend_chain(preferred)

    for index, name in enumerate(chain):
        if name == "deepl" and not os.environ.get("DEEPL_API_KEY"):
            logger.warning("backend 'deepl' skipped: DEEPL_API_KEY is not set")
            continue
        if name == "libretranslate_remote" and not os.environ.get("LIBRETRANSLATE_URL"):
            logger.warning(
                "backend 'libretranslate_remote' skipped: LIBRETRANSLATE_URL is not set"
            )
            continue

        try:
            factory = _BACKEND_FACTORIES[name]
            translator = factory(source, target, script_path)
            if index:
                print(
                    f"⚠️  Backend '{chain[index - 1]}' unavailable — "
                    f"falling back to '{name}'."
                )
            logger.info("selected backend: {}", name)
            return name, translator
        except Exception as exc:
            last_error = str(exc)
            logger.warning("backend '{}' unavailable: {}", name, exc)

    raise BackendError(f"no usable translation backend found: {last_error}")


def _load_existing(path: Path) -> "OrderedDict[str, str]":
    """Load an existing JSON mapping without printing its potentially large contents."""
    if not path.exists():
        return OrderedDict()

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle, object_pairs_hook=OrderedDict)
        if not isinstance(loaded, dict):
            raise ValueError("JSON root must be an object")
        return OrderedDict((str(key), str(value)) for key, value in loaded.items())
    except Exception as exc:
        raise BackendError(f"cannot load existing output '{path}': {exc}") from exc


def _read_pending(
    input_path: Path, existing: Dict[str, str], continue_job: bool
) -> Tuple[List[str], int]:
    """Stream the input once and return unique pending words plus total input count."""
    if not input_path.is_file():
        raise BackendError(f"input file does not exist: {input_path}")

    pending: List[str] = []
    seen_pending = set()
    total = 0

    with input_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            word = raw_line.rstrip("\r\n")
            if not word.strip():
                continue
            total += 1
            if continue_job and word in existing:
                continue
            if word not in seen_pending:
                pending.append(word)
                seen_pending.add(word)

    return pending, total


def _atomic_save(path: Path, results: Dict[str, str]) -> None:
    """Write the current mapping to a temporary file and atomically replace output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    directory = str(path.parent)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _append_failed(path: Path, word: str) -> None:
    """Append one failed word safely so concurrent workers cannot interleave lines."""
    with _failed_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(word + "\n")


def _is_valid_translation(source: str, translated: object) -> bool:
    """Return whether a backend result is nonempty and not an identity translation."""
    if translated is None:
        return False
    value = str(translated).strip()
    return bool(value) and value.casefold() != source.casefold()


def _translate_one(
    word: str,
    translator: TranslationFunction,
    delay: float,
    failed_path: Path,
) -> Tuple[str, Optional[str]]:
    """Translate one word with three attempts and exponential retry backoff."""
    last_error = "empty or identity translation"

    for attempt in range(1, 4):
        try:
            # Delay before every network request, including retries.
            if delay:
                time.sleep(delay)

            raw_result = translator(word)
            with _console_lock:
                print(f"{word} -> {raw_result}")

            if _is_valid_translation(word, raw_result):
                return word, str(raw_result)

            last_error = "backend returned an empty or identity translation"
            raise BackendError(last_error)
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "attempt {}/3 failed for {!r}: {}",
                attempt,
                word,
                last_error,
            )
            if attempt < 3:
                time.sleep(0.5 * (2 ** (attempt - 1)))

    _append_failed(failed_path, word)
    logger.error("giving up on {!r} after 3 attempts: {}", word, last_error)
    return word, None


def _print_progress(
    number: int, total: int, word: str, translation: Optional[str]
) -> None:
    """Print one compact, serialized progress line to stdout."""
    with _console_lock:
        if translation is None:
            print(f"[{number}/{total}] ✗ {word} (failed -> failed.txt)")
        else:
            print(f"[{number}/{total}] ✓ {word} -> {translation}")


def _parse_args() -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Translate a word-list file into a JSON mapping on Termux."
    )
    parser.add_argument("-i", "--input", default="words.txt")
    parser.add_argument("-o", "--output", default="words.json")
    parser.add_argument("--failed", default="failed.txt")
    parser.add_argument("-s", "--source", default="fr")
    parser.add_argument("-t", "--target", default="en")
    parser.add_argument(
        "-b",
        "--backend",
        default="default",
        help=(
            "preferred backend; default uses the Termux fallback chain "
            "(the documented default chain starts with deepl when configured)"
        ),
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=2,
        help="concurrent worker threads (default: 2)",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0.5,
        help="delay before each request per worker (default: 0.5)",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=50,
        help="save after this many completed words (default: 50)",
    )
    parser.add_argument(
        "--no-continue",
        action="store_true",
        help="ignore an existing output file and start fresh",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.save_every < 1:
        parser.error("--save-every must be at least 1")

    return args


def main() -> int:
    """Run the translation job and return a process exit status."""
    _configure_logging()
    args = _parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    failed_path = Path(args.failed)
    script_path = str(Path(__file__).resolve())

    try:
        existing = OrderedDict() if args.no_continue else _load_existing(output_path)
        pending, total = _read_pending(
            input_path,
            existing,
            continue_job=not args.no_continue,
        )
        results = OrderedDict(existing)

        if not args.no_continue:
            with _console_lock:
                print(f"Loaded {len(existing)} existing translations.")

        backend_name, translator = _select_backend(
            args.backend,
            args.source,
            args.target,
            script_path,
        )

        with _console_lock:
            print(
                f"Using backend '{backend_name}'. "
                f"{len(pending)} words pending out of {total}."
            )

        if not pending:
            with _results_lock:
                _atomic_save(output_path, results)
            print(f"Nothing to translate; progress is saved in {output_path}.")
            return 0

        completed = 0
        # The executor bounds the number of active requests and keeps memory use low.
        with ThreadPoolExecutor(
            max_workers=args.workers,
            thread_name_prefix="translator",
        ) as executor:
            futures = {
                executor.submit(
                    _translate_one,
                    word,
                    translator,
                    args.delay,
                    failed_path,
                ): word
                for word in pending
            }

            try:
                for future in as_completed(futures):
                    word, translation = future.result()
                    with _counter_lock:
                        completed += 1
                        number = completed

                    if translation is not None:
                        with _results_lock:
                            results[word] = translation

                    _print_progress(number, len(pending), word, translation)

                    if completed % args.save_every == 0:
                        with _results_lock:
                            _atomic_save(output_path, results)
                        logger.info("checkpoint saved after {} words", completed)
            except KeyboardInterrupt:
                logger.warning("interrupt received; cancelling unfinished work")
                for future in futures:
                    future.cancel()
                with _results_lock:
                    _atomic_save(output_path, results)
                print(f"\nInterrupted. Progress saved to {output_path}.")
                return 130

        with _results_lock:
            _atomic_save(output_path, results)

        print(f"Finished. Results saved to {output_path}.")
        print(f"Words that failed all retries were appended to {failed_path}.")
        print(
            "Next steps: for offline-style use, run LibreTranslate on a PC, "
            "VPS, or Raspberry Pi on the LAN and set LIBRETRANSLATE_URL."
        )
        return 0

    except KeyboardInterrupt:
        # This outer handler covers interrupts during startup/backend selection.
        if "results" in locals():
            with _results_lock:
                _atomic_save(output_path, results)
            print(f"\nInterrupted. Progress saved to {output_path}.")
        else:
            print("\nInterrupted before translation started.")
        return 130
    except BackendError as exc:
        logger.error("{}", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        logger.exception("unexpected fatal error")
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
