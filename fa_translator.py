#!/data/data/com.termux/files/home/.local/bin/python
"""
merged_translator.py — unified Persian ↔ English translation toolkit.

Merges the behavior of nine small scripts that each did one slice of the
same job (translate Persian text to English, or look up words in a small
offline JSON dictionary).

Third-party packages (install what you need):
    pip install deep-translator          # used by most backends
    pip install translate                # only for --backend translate-package
    pip install tqdm                     # optional progress bar for `words`
    pip install loguru                   # NOT required (stdlib logging is used)

Optional external tools:
    translate-cli     # only for --backend translate-cli
    fzf               # only used by `lookup` (auto-detected, safe if absent)

-------------------------------------------------------------------------------
USAGE
-------------------------------------------------------------------------------
    python merged_translator.py file   INPUT  [options]
    python merged_translator.py words  INPUT  [options]
    python merged_translator.py lookup [WORD] [options]

-------------------------------------------------------------------------------
ORIGINAL → MERGED MAPPING
-------------------------------------------------------------------------------
    fa_trans.py     ->  file IN --mode line --persian-only --in-place \
                            --workers 8 --source fa --target en
    transwords.py   ->  file IN --mode chunk --chunk-size 4500 \
                            --output-format chunks --workers 8
    runtcli.py      ->  file IN --mode line --backend translate-cli \
                            --source en --target fa --output-format numbered
    tfa.py          ->  words words.txt --output dic.json --workers 1 \
                            --no-resume --no-dedupe
    tper.py         ->  words words.txt --output dic.json --workers 8 \
                            --resume --dedupe --save-every 1000
    trans_fa_mp.py  ->  words words.txt --output dic.json --executor thread \
                            --workers 16 --no-resume
    tcli.py         ->  words words.txt --backend translate-package \
                            --source en --target fa --output words.fa.json
    fatrans.py      ->  lookup --dict /sdcard/isaac/dic.json --no-fzf
    fztrans.py      ->  lookup --dict ~/dic.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Optional third-party packages (all already required by at least one original)
# ---------------------------------------------------------------------------
try:
    from deep_translator import GoogleTranslator
except ImportError:  # pragma: no cover - optional dependency
    GoogleTranslator = None  # type: ignore[assignment]

try:
    from translate import Translator as PyTranslator  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    PyTranslator = None  # type: ignore[assignment]

try:
    from tqdm import tqdm  # type: ignore
except ImportError:  # pragma: no cover - optional dependency

    class _DummyTqdm:
        """No-op replacement for `tqdm.tqdm` when the package is unavailable."""

        def __init__(self, *_: Any, **__: Any) -> None:  # noqa: D401
            pass

        def update(self, _n: int = 1) -> None:
            pass

        def close(self) -> None:
            pass

        def __enter__(self) -> "_DummyTqdm":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    def tqdm(iterable: Any = None, *_: Any, **__: Any) -> Any:  # type: ignore
        if iterable is not None and hasattr(iterable, "__iter__"):
            return iterable
        return _DummyTqdm()


try:
    import readline  # noqa: F401  (side-effect import enables line editing)

    _HAVE_READLINE = True
except ImportError:  # pragma: no cover - platform dependent
    _HAVE_READLINE = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("merged_translator")


def setup_logging(verbose: bool = False) -> None:
    """Configure the root logger once. `--verbose` bumps to DEBUG."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Persian text detection (identical regex to the originals)
# ---------------------------------------------------------------------------
PERSIAN_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def is_persian(text: str) -> bool:
    """Return True if `text` contains at least one Persian/Arabic character."""
    return bool(PERSIAN_RE.search(text))


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def load_json_dict(path: Path) -> dict[str, str]:
    """Load a JSON file, coerce it to a flat `{str: str}` dict."""
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return {str(k).strip(): str(v).strip() for k, v in data.items()}


def save_json(data: Any, path: Path) -> None:
    """Atomic-ish JSON write: write to `*.tmp`, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Translation backends — uniform signature
#   (text, source, target, retries, delay) -> Optional[str]
# ---------------------------------------------------------------------------
def translate_google(
    text: str,
    source: str = "auto",
    target: str = "en",
    retries: int = 3,
    delay: float = 0.5,
) -> Optional[str]:
    """Backend: `deep_translator.GoogleTranslator` (with retry loop)."""
    if GoogleTranslator is None:
        raise RuntimeError(
            "deep-translator is not installed (pip install deep-translator)"
        )
    translator = GoogleTranslator(source=source, target=target)
    for attempt in range(retries):
        try:
            result = translator.translate(text)
            if result:
                return result
        except Exception as exc:  # noqa: BLE001 - we retry on any failure
            log.warning(
                "google translate failed for %r (attempt %d/%d): %s",
                text[:40],
                attempt + 1,
                retries,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(delay)
    return None


def translate_pypackage(
    text: str,
    source: str = "en",
    target: str = "fa",
    retries: int = 1,
    delay: float = 0.5,
) -> Optional[str]:
    """Backend: `translate.Translator` (PyPI package `translate`)."""
    if PyTranslator is None:
        raise RuntimeError("translate package is not installed (pip install translate)")
    translator = PyTranslator(from_lang=source, to_lang=target)
    for attempt in range(retries):
        try:
            result = translator.translate(text)
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "translate-package failed for %r (attempt %d/%d): %s",
                text[:40],
                attempt + 1,
                retries,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(delay)
    return None


def translate_cli(
    text: str,
    source: str = "en",
    target: str = "fa",
    retries: int = 1,
    delay: float = 0.5,
) -> Optional[str]:
    """Backend: the external `translate-cli` binary."""
    cmd = ["translate-cli", "-f", source, "-t", target, "-o", text]
    last_err = ""
    for attempt in range(retries):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return "__ERROR__: translate-cli not found in PATH"
        except Exception as exc:  # noqa: BLE001
            return f"__ERROR__: {exc}"
        if proc.returncode == 0:
            return proc.stdout.strip()
        last_err = proc.stderr.strip()
        if attempt < retries - 1:
            time.sleep(delay)
    return f"__ERROR__: {last_err}"


_BACKENDS = {
    "deep-translator": translate_google,
    "translate-package": translate_pypackage,
    "translate-cli": translate_cli,
}


def get_backend(name: str):
    """Return the translation callable registered under `name`."""
    try:
        return _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"unknown backend: {name!r} (choose from {sorted(_BACKENDS)})"
        ) from None


# ---------------------------------------------------------------------------
# Worker used by BOTH thread- and process-pools.
# Must be module-level so it can be pickled by ProcessPoolExecutor.
# ---------------------------------------------------------------------------
def _translate_item(
    item: tuple[str, str, str, str, int, float],
) -> tuple[str, Optional[str]]:
    """Translate one text unit. Returns `(input, output_or_None)`.

    Tuple layout: (text, backend_name, source, target, retries, delay).
    """
    text, backend_name, source, target, retries, delay = item
    try:
        backend = get_backend(backend_name)
        result = backend(
            text, source=source, target=target, retries=retries, delay=delay
        )
    except Exception as exc:  # noqa: BLE001 - don't kill the whole pool
        log.warning("worker error for %r: %s", text[:40], exc)
        result = None
    return text, result


# ---------------------------------------------------------------------------
# `file` subcommand helpers
# ---------------------------------------------------------------------------
def split_into_chunks(lines: list[str], max_chars: int) -> list[tuple[int, int, str]]:
    """Group `lines` into chunks of at most `max_chars` characters.

    Oversized single lines are emitted as their own chunk (matches the
    behavior of the originals).
    """
    chunks: list[tuple[int, int, str]] = []
    buf: list[str] = []
    buf_len = 0
    start = 0
    for i, line in enumerate(lines):
        n = len(line) + 1  # +1 accounts for the newline that will be added
        if buf_len + n > max_chars and buf:
            chunks.append((start, i - 1, "\n".join(buf)))
            buf, buf_len, start = [], 0, i
        if n > max_chars:
            if buf:
                chunks.append((start, i - 1, "\n".join(buf)))
                buf, buf_len, start = [], 0, i
            chunks.append((i, i, line))
            start = i + 1
        else:
            buf.append(line)
            buf_len += n
    if buf:
        chunks.append((start, len(lines) - 1, "\n".join(buf)))
    return chunks


def cmd_file(args: argparse.Namespace) -> int:
    """Translate a text file (line-by-line or chunked). See module docstring."""
    input_path = Path(args.input)
    if not input_path.is_file():
        log.error("Input file not found: %s", input_path)
        return 1

    try:
        raw_lines = input_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # noqa: BLE001
        log.error("Error reading %s: %s", input_path, exc)
        return 1

    lines = [ln.strip() for ln in raw_lines if ln.strip()]
    if not lines:
        print(f"No lines found in {input_path.name}")
        return 0

    # Optional Persian-only filtering (fa_trans behavior)
    if args.persian_only:
        pending = [ln for ln in lines if is_persian(ln)]
        skipped = len(lines) - len(pending)
    else:
        pending = list(lines)
        skipped = 0

    print(f"Loaded {len(lines)} lines: {len(pending)} to translate, {skipped} skipped")
    if not pending:
        print("Nothing to translate.")
        return 0

    # --- build units of work ---
    backend_name = args.backend
    source, target = args.source, args.target
    retries, delay = args.retries, args.delay

    if args.mode == "line":
        work_units = list(pending)
    else:
        work_units = [
            text for _s, _e, text in split_into_chunks(pending, args.chunk_size)
        ]

    print(
        f"Translating {len(work_units)} unit(s) with {args.workers} workers "
        f"via {backend_name} ({args.executor})..."
    )

    PoolClass = ThreadPoolExecutor if args.executor == "thread" else ProcessPoolExecutor
    packed = [
        (text, backend_name, source, target, retries, delay) for text in work_units
    ]

    results: list[tuple[str, Optional[str]]] = []
    try:
        with PoolClass(max_workers=args.workers) as pool:
            futures = [pool.submit(_translate_item, item) for item in packed]
            for i, fut in enumerate(futures, 1):
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    log.error("Unexpected worker error: %s", exc)
                    results.append(("", None))
                if args.progress and (i % 5 == 0 or i == len(futures)):
                    print(f"  progress: {i}/{len(futures)}")
    except KeyboardInterrupt:
        print("Interrupted by user.")
        return 130

    # --- collapse results into {orig_line: translated_line} ---
    translations: dict[str, str] = {}
    if args.mode == "line":
        for orig, trans in results:
            if trans:
                translations[orig] = trans
    else:
        for chunk_text, trans in results:
            if not trans:
                continue
            src_lines = chunk_text.split("\n")
            dst_lines = trans.split("\n")
            for i, src_line in enumerate(src_lines):
                if i < len(dst_lines):
                    translations[src_line] = dst_lines[i]
                else:
                    log.error(
                        "Line-count mismatch in chunk, missing translation for: %s",
                        src_line[:50],
                    )

    if not translations:
        log.error("No translations were produced.")
        return 1

    # --- write JSON output ---
    output_path = Path(args.output) if args.output else input_path.with_suffix(".json")

    if args.output_format == "chunks" and args.mode == "chunk":
        payload: Any = {
            "translations": [
                {
                    "chunk_id": str(i),
                    "original": orig,
                    "translated": trans,
                }
                for i, (orig, trans) in enumerate(results)
                if trans
            ]
        }
    elif args.output_format == "numbered":
        payload = [
            {
                "line_number": i + 1,
                "source": src,
                "translation": translations.get(src),
            }
            for i, src in enumerate(pending)
        ]
    else:  # "dict"
        payload = translations

    try:
        save_json(payload, output_path)
        print(f"Saved {len(translations)} translations to {output_path.name}")
    except Exception as exc:  # noqa: BLE001
        log.error("Error saving JSON: %s", exc)

    # --- optional in-place rewrite ---
    if args.in_place:
        try:
            out_lines = [translations.get(ln, ln) for ln in lines]
            input_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            print(f"Updated {input_path.name}")
        except Exception as exc:  # noqa: BLE001
            log.error("Error updating input file: %s", exc)
            return 1

    return 0


# ---------------------------------------------------------------------------
# `words` subcommand
# ---------------------------------------------------------------------------
def cmd_words(args: argparse.Namespace) -> int:
    """Translate a words file into a `{word: translation}` JSON dict."""
    input_path = Path(args.input)
    if not input_path.is_file():
        log.error("Input file not found: %s", input_path)
        return 1

    output_path = Path(args.output)

    # --- read + optional dedupe ---
    seen: set[str] = set()
    words: list[str] = []
    for raw in input_path.read_text(encoding="utf-8").splitlines():
        w = raw.strip()
        if not w:
            continue
        if args.dedupe and w in seen:
            continue
        seen.add(w)
        words.append(w)

    if not words:
        print(f"No words found in {input_path}")
        return 0

    print(f"Loaded {len(words)} words from {input_path}")

    # --- optional resume ---
    existing: dict[str, str] = {}
    if args.resume and output_path.exists():
        try:
            existing = load_json_dict(output_path)
            print(f"Loaded {len(existing)} existing translations from {output_path}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load existing %s: %s", output_path, exc)

    pending = [w for w in words if w not in existing]
    print(
        f"{len(pending)} to translate "
        f"(skipping {len(words) - len(pending)} already translated)"
    )
    if not pending:
        print("Nothing to do.")
        return 0

    results: dict[str, str] = dict(existing)
    progress = tqdm(total=len(pending), desc="Translating", unit="word")

    PoolClass = ThreadPoolExecutor if args.executor == "thread" else ProcessPoolExecutor
    packed = [
        (w, args.backend, args.source, args.target, args.retries, args.delay)
        for w in pending
    ]

    saved_count = 0
    try:
        with PoolClass(max_workers=args.workers) as pool:
            futures = [pool.submit(_translate_item, item) for item in packed]
            for fut in as_completed(futures):
                try:
                    word, trans = fut.result()
                except Exception as exc:  # noqa: BLE001
                    log.error("Worker error: %s", exc)
                    progress.update(1)
                    continue

                is_error = isinstance(trans, str) and trans.startswith("__ERROR__")
                if trans and not is_error:
                    results[word] = trans
                    print(f"{word} → {trans}")
                    saved_count += 1
                else:
                    log.error("Could not translate: %s", word)

                progress.update(1)

                if (
                    args.save_every
                    and saved_count
                    and (saved_count % args.save_every == 0)
                ):
                    try:
                        save_json(results, output_path)
                        log.info("Checkpoint: saved %d entries", len(results))
                    except Exception as exc:  # noqa: BLE001
                        log.error("Checkpoint save failed: %s", exc)
    except KeyboardInterrupt:
        print("Interrupted by user. Saving progress...")
    finally:
        progress.close()
        try:
            save_json(results, output_path)
            print(f"Saved {len(results)} entries to {output_path}")
        except Exception as exc:  # noqa: BLE001
            log.error("Error saving results: %s", exc)
            return 1

    failures = len(pending) - saved_count
    if failures:
        log.warning("%d entr(ies) failed.", failures)
    return 0


# ---------------------------------------------------------------------------
# `lookup` subcommand
# ---------------------------------------------------------------------------
def _setup_readline(candidates: list[str]) -> None:
    """Install a tab-completer over `candidates` (no-op if readline absent)."""
    if not _HAVE_READLINE:
        return
    words = sorted(candidates)

    def completer(text: str, state: int) -> Optional[str]:
        matches = [w for w in words if w.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n")


def _load_dictionary(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load `{fa: en}` (or `{en: fa}`) JSON and build the reverse map."""
    if not path.exists():
        log.error("Dictionary file not found: %s", path)
        sys.exit(1)
    try:
        fwd = load_json_dict(path)
    except Exception as exc:  # noqa: BLE001
        log.error("Error loading dictionary: %s", exc)
        sys.exit(1)
    rev = {v: k for k, v in fwd.items()}
    return fwd, rev


def _fuzzy(
    word: str,
    candidates: Iterable[str],
    n: int = 5,
    cutoff: float = 0.6,
) -> list[str]:
    """`difflib.get_close_matches` wrapper used by the lookup command."""
    return get_close_matches(word, list(candidates), n=n, cutoff=cutoff)


def _fzf_select(
    candidates: Iterable[str], prompt: str = "Select word: "
) -> Optional[str]:
    """Run `fzf` interactively; return the selected string or None."""
    if not shutil.which("fzf"):
        return None
    try:
        proc = subprocess.run(
            [
                "fzf",
                f"--prompt={prompt}",
                "--height=40%",
                "--layout=reverse",
                "--border",
            ],
            input="\n".join(sorted(candidates)),
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("fzf execution error: %s", exc)
        return None
    out = proc.stdout.strip()
    return out or None


def _interactive_loop(fwd: dict[str, str], rev: dict[str, str]) -> int:
    """REPL for offline lookups (tab completion + fuzzy fallback)."""
    candidates = set(fwd) | set(rev)
    _setup_readline(list(candidates))
    print("\n🌐 Offline Persian ↔ English Translator")
    print("⌨  TAB for suggestions, Ctrl+C to exit\n")
    while True:
        try:
            query = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Bye.")
            return 0
        if not query:
            continue
        hit = fwd.get(query) or rev.get(query)
        if hit:
            print(f"✅ {hit}")
            continue
        matches = _fuzzy(query, candidates)
        if matches:
            print(f"❓ Not found. Did you mean: {', '.join(matches)}?")
        else:
            print("❌ Not found")


def cmd_lookup(args: argparse.Namespace) -> int:
    """Offline dictionary lookup (mirrors `fatrans.py` and `fztrans.py`)."""
    dict_path = Path(os.path.expanduser(args.dict))
    fwd, rev = _load_dictionary(dict_path)
    candidates = set(fwd) | set(rev)

    # --prefix
    if args.prefix:
        matches = sorted(w for w in candidates if w.startswith(args.prefix))
        if matches:
            print("\n".join(matches))
            return 0
        print(f"No matches found for prefix: {args.prefix}")
        return 1

    # --fuzzy
    if args.fuzzy:
        matches = _fuzzy(args.fuzzy, candidates)
        if matches:
            print("\n".join(matches))
            return 0
        print(f"No close matches found for: {args.fuzzy}")
        return 1

    # positional word(s)
    if args.word:
        word = " ".join(args.word).strip()
        hit = fwd.get(word) or rev.get(word)
        if hit:
            print(hit)
            return 0
        matches = _fuzzy(word, candidates)
        if matches:
            print(
                f"Not found. Did you mean: {', '.join(matches)}?",
                file=sys.stderr,
            )
        else:
            print("Not found", file=sys.stderr)
        return 1

    # Interactive: try fzf first unless disabled
    if not args.no_fzf:
        selected = _fzf_select(candidates)
        if selected:
            hit = fwd.get(selected) or rev.get(selected)
            print(f"{selected} → {hit}")
            return 0
        if shutil.which("fzf"):
            # fzf was available and user cancelled → exit cleanly
            return 0

    return _interactive_loop(fwd, rev)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="merged_translator.py",
        description="Unified Persian ↔ English translation toolkit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  merged_translator.py file notes.txt --persian-only --in-place\n"
            "  merged_translator.py file big.txt --mode chunk --output-format chunks\n"
            "  merged_translator.py words words.txt --output dic.json --workers 8\n"
            "  merged_translator.py lookup --prefix کتاب\n"
            "  merged_translator.py lookup\n"
        ),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- file ----
    p_file = sub.add_parser(
        "file",
        help="Translate a text file (line-by-line or chunked).",
    )
    p_file.add_argument("input", help="Path to the input text file")
    p_file.add_argument(
        "--mode",
        choices=["line", "chunk"],
        default="line",
        help="Translate each line independently (default) or in chunks",
    )
    p_file.add_argument(
        "--chunk-size",
        type=int,
        default=4500,
        help="Max characters per chunk in --mode chunk (default: 4500)",
    )
    p_file.add_argument(
        "--backend",
        choices=sorted(_BACKENDS),
        default="deep-translator",
        help="Translation backend (default: deep-translator)",
    )
    p_file.add_argument("--source", default="fa", help="Source language")
    p_file.add_argument("--target", default="en", help="Target language")
    p_file.add_argument(
        "--workers", type=int, default=8, help="Parallel workers (default: 8)"
    )
    p_file.add_argument(
        "--executor",
        choices=["process", "thread"],
        default="thread",
        help="Pool kind (default: thread)",
    )
    p_file.add_argument(
        "--persian-only",
        action="store_true",
        help="Only translate lines that contain Persian characters",
    )
    p_file.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the input file with translations",
    )
    p_file.add_argument(
        "--output",
        default=None,
        help="JSON output path (default: <input>.json)",
    )
    p_file.add_argument(
        "--output-format",
        choices=["dict", "chunks", "numbered"],
        default="dict",
        help="JSON shape (default: dict)",
    )
    p_file.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per translation unit (default: 3)",
    )
    p_file.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5)",
    )
    p_file.add_argument(
        "--progress", action="store_true", help="Print periodic progress lines"
    )
    p_file.set_defaults(func=cmd_file)

    # ---- words ----
    p_words = sub.add_parser(
        "words", help="Translate a word list into a JSON dictionary."
    )
    p_words.add_argument("input", help="Path to the words file")
    p_words.add_argument(
        "--output",
        default="dic.json",
        help="Output JSON dict (default: dic.json)",
    )
    p_words.add_argument(
        "--backend",
        choices=sorted(_BACKENDS),
        default="deep-translator",
        help="Translation backend (default: deep-translator)",
    )
    p_words.add_argument(
        "--source", default="auto", help="Source language (default: auto)"
    )
    p_words.add_argument("--target", default="en", help="Target language (default: en)")
    p_words.add_argument(
        "--workers", type=int, default=8, help="Parallel workers (default: 8)"
    )
    p_words.add_argument(
        "--executor",
        choices=["process", "thread"],
        default="thread",
        help="Pool kind (default: thread)",
    )
    p_words.add_argument(
        "--dedupe",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Remove duplicate words (default: on)",
    )
    p_words.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip words already present in --output (default: on)",
    )
    p_words.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per word (default: 3)",
    )
    p_words.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5)",
    )
    p_words.add_argument(
        "--save-every",
        type=int,
        default=1000,
        help="Checkpoint the output after N new translations (0 disables)",
    )
    p_words.set_defaults(func=cmd_words)

    # ---- lookup ----
    p_lookup = sub.add_parser(
        "lookup", help="Offline dictionary lookup (with optional fzf)."
    )
    p_lookup.add_argument("word", nargs="*", help="Word(s) to translate")
    p_lookup.add_argument(
        "--dict",
        default="~/dic.json",
        help="Path to the JSON dictionary (default: ~/dic.json)",
    )
    p_lookup.add_argument(
        "--prefix", default=None, help="List words starting with this prefix"
    )
    p_lookup.add_argument("--fuzzy", default=None, help="Fuzzy-search this string")
    p_lookup.add_argument(
        "--no-fzf",
        action="store_true",
        help="Disable the interactive fzf picker",
    )
    p_lookup.set_defaults(func=cmd_lookup)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point: parse args, configure logging, dispatch to subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
