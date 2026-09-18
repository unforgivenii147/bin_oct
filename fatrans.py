#!/data/data/com.termux/files/home/.local/bin/python
"""
Unified translation toolkit.

Merged from four scripts that all wrap `deep_translator.GoogleTranslator`
with slightly different pipelines.  Every original behaviour is still
reachable as a subcommand; the differing knobs are CLI flags.

Third-party dependencies (only these are needed at runtime):
    pip install deep-translator tqdm loguru

------------------------------------------------------------------------------
Subcommand → original-script mapping
------------------------------------------------------------------------------
    tofa.py       ->  python translator.py to-fa <input> [source]
    transfa.py    ->  python translator.py lines-to-en <input>
    transfa2.py   ->  python translator.py inplace-to-en [path]
    transfamp.py  ->  python translator.py batch-json [directory]

------------------------------------------------------------------------------
Examples
------------------------------------------------------------------------------
    # Translate a file into Farsi, auto-detecting the source language
    python translator.py to-fa document.txt

    # Same, but force source language to English and use a smaller chunk size
    python translator.py to-fa file.txt en --chunk-size 3000

    # Translate a Farsi file line-by-line into English
    python translator.py lines-to-en notes.txt --workers 6

    # Recursively translate Farsi content inside every supported file in ./src
    python translator.py inplace-to-en ./src --workers 8

    # Batch-translate every *.txt in the current directory into JSON maps
    python translator.py batch-json --glob "*.txt" --out-dir ./translations
"""

from __future__ import annotations

# --- stdlib ---------------------------------------------------------------
import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

# --- third-party ----------------------------------------------------------
from deep_translator import GoogleTranslator
from loguru import logger
from tqdm import tqdm


# ===========================================================================
# Constants (defaults mirror the original scripts; all overridable via CLI)
# ===========================================================================

#: Farsi/Arabic unicode ranges used by all three original scripts, merged.
FARSI_RE: re.Pattern[str] = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

#: Marker-priority break points used by tofa.py (order matters — first match wins).
TOFA_MARKERS: tuple[str, ...] = (
    "\n",
    "\r\n",
    ".  ",
    "!  ",
    "?  ",
    "; ",
    ", ",
    " ",
)

#: Regex break points used by transfa2.py.
INPLACE_BREAK_RE: re.Pattern[str] = re.compile(r"[\s\n\.\!\?\;]+")

#: File suffixes transfa2.py scans by default.
DEFAULT_SUFFIXES: tuple[str, ...] = (".txt", ".md", ".py", ".json", ".csv")

#: Directory names transfa2.py skips by default.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    "lazy",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
)


# ===========================================================================
# Shared helpers
# ===========================================================================


def read_text_any_encoding(path: Path) -> str:
    """Read *path* trying a list of encodings (used by tofa.py)."""
    for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except (OSError, UnicodeDecodeError):
            continue
    raise OSError(f"Could not read file {path} with any encoding")


def contains_farsi(text: str) -> bool:
    """Return True if *text* contains at least one Farsi/Arabic codepoint."""
    return bool(FARSI_RE.search(text))


def derive_output_path(src: Path, suffix: str) -> Path:
    """`notes.txt` + suffix=`fa` → `notes_fa.txt`."""
    return src.parent / f"{src.stem}_{suffix}{src.suffix}"


def translate_with_retry(
    text: str,
    source: str = "auto",
    target: str = "fa",
    retries: int = 3,
    base_delay: float = 1.0,
) -> str:
    """
    Translate *text* with up to *retries* attempts.

    Mirrors the retry loop from tofa.py: exponential-ish backoff
    `base_delay + attempt`.
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            result = GoogleTranslator(source=source, target=target).translate(text)
            if result is None:
                raise RuntimeError("Translator returned None")
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(
                f"[WARN] Translation failed (attempt {attempt + 1}/{retries}): {exc}",
                file=sys.stderr,
            )
            time.sleep(base_delay + attempt)
    raise RuntimeError(f"Translation failed after {retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------


def chunk_by_markers(
    text: str,
    max_chars: int,
    markers: Sequence[str] = TOFA_MARKERS,
) -> list[str]:
    """
    tofa.py-style chunker.

    For each window of *max_chars* characters, look for the first marker in
    *markers* (priority order, not position order) and cut just after its
    **last** occurrence inside the window.  Falls back to the last space,
    then hard-cuts at *max_chars*.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    pos = 0
    while pos < len(text):
        remaining = text[pos:]
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        head = remaining[:max_chars]
        cut = max_chars
        for marker in markers:
            idx = head.rfind(marker)
            if idx > 0:
                cut = idx + len(marker)
                break
        else:
            idx = head.rfind(" ")
            if idx > 0:
                cut = idx + 1

        chunks.append(remaining[:cut])
        pos += cut

    return chunks


def chunk_by_regex(
    text: str,
    max_chars: int,
    pattern: re.Pattern[str] = INPLACE_BREAK_RE,
) -> list[str]:
    """
    transfa2.py-style chunker.

    Cut at the **last** regex match that falls entirely inside the window.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    pos = 0
    while pos < len(text):
        end = min(pos + max_chars, len(text))
        if end == len(text):
            chunks.append(text[pos:])
            break

        last = None
        for match in pattern.finditer(text, pos, end):
            last = match

        cut = last.end() if (last is not None and last.end() > pos) else end
        chunks.append(text[pos:cut])
        pos = cut

    return chunks


def collect_files(
    root: Path,
    suffixes: Iterable[str],
    exclude: Iterable[str],
) -> list[Path]:
    """Recursively gather files whose suffix is in *suffixes* (transfa2.py)."""
    suffix_set = {s.lower() for s in suffixes}
    exclude_set = set(exclude)
    found: list[Path] = []
    for p in root.rglob("*"):
        if any(part.startswith(".") or part in exclude_set for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in suffix_set:
            found.append(p)
    return sorted(found)


# ===========================================================================
# Multiprocessing workers (must be module-level to be picklable)
# ===========================================================================


def _worker_line_to_en(line: str) -> Optional[tuple[str, str]]:
    """transfa.py worker: translate a single Farsi line to English."""
    stripped = line.strip()
    if not stripped or not contains_farsi(stripped):
        return None
    try:
        result = GoogleTranslator(source="fa", target="en").translate(stripped)
        return (stripped, result) if result else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Translation error for '{stripped[:20]}': {exc}")
        return None


def _worker_chunk_to_en(payload: tuple[str, float]) -> str:
    """transfa2.py worker: translate one chunk in place."""
    chunk, sleep_sec = payload
    if not contains_farsi(chunk):
        return chunk
    try:
        result = GoogleTranslator(source="fa", target="en").translate(chunk)
        if result:
            preview = result[:30].replace("\n", " ")
            print(f"Chunk translated: {preview}...")
            time.sleep(sleep_sec)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Chunk translation error: {exc}")
    return chunk


def _worker_file_to_dict(path: Path) -> tuple[Path, dict[str, str]]:
    """transfamp.py worker: translate one .txt file into a {orig: trans} map."""
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            logger.warning(f"⚠️  Empty file: {path.name}")
            return (path, {})

        translated = GoogleTranslator(source="fa", target="en").translate(content)
        if translated is None:
            translated = ""

        src_lines = [l.strip() for l in content.split("\n") if l.strip()]
        out_lines = [l.strip() for l in translated.split("\n") if l.strip()]

        mapping: dict[str, str] = {}
        if len(src_lines) != len(out_lines):
            # Fallback: translate each line individually.
            for i, line in enumerate(src_lines):
                if not line:
                    continue
                try:
                    res = GoogleTranslator(source="fa", target="en").translate(line)
                    mapping[line] = res or ""
                except Exception as exc:  # noqa: BLE001
                    mapping[line] = f"TRANSLATION_ERROR: {exc}"
                    logger.warning(
                        f"  ⚠️  Error translating line {i + 1} in {path.name}: {exc}"
                    )
        else:
            mapping = dict(zip(src_lines, out_lines))

        print(f"✅ Translated: {path.name} ({len(mapping)} words)")
        return (path, mapping)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Error processing {path.name}: {exc}")
        return (path, {})


# ===========================================================================
# Subcommand implementations
# ===========================================================================


def cmd_to_fa(args: argparse.Namespace) -> int:
    """
    Equivalent to ``tofa.py``.

    Read a file (any of several encodings), translate it to Farsi, and write
    ``<stem>_<output_suffix><suffix>``.  Large files are chunked.
    """
    src = Path(args.input)
    if not src.exists():
        logger.error(f"File not found: {src}")
        return 1

    dst = derive_output_path(src, args.output_suffix)
    if dst.exists() and not args.overwrite:
        print(f"[INFO] Output file already exists: {dst}")
        print(f"[INFO] Skipping translation (use --overwrite to re-run)")
        return 0

    print(f"[INFO] Reading file: {src}")
    try:
        content = read_text_any_encoding(src)
    except OSError as exc:
        logger.error(str(exc))
        return 1

    print(f"[INFO] File size: {len(content)} characters")
    print(f"[INFO] Input:   {src}")
    print(f"[INFO] Output:  {dst}")
    print(f"[INFO] Source language: {args.source}")

    try:
        translated = _translate_file_to_target(
            content,
            source=args.source,
            target=args.target,
            chunk_size=args.chunk_size,
            retries=args.retries,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Translation failed: {exc}")
        return 1

    print(f"\n[INFO] Saving result to: {dst}")
    dst.write_text(translated, encoding="utf-8")
    print("\n[SUCCESS] Translation complete!")
    print(f"[INFO] Output file: {dst}")
    print(f"[INFO] Output size: {len(translated)} characters")
    return 0


def _translate_file_to_target(
    content: str,
    source: str,
    target: str,
    chunk_size: int,
    retries: int,
) -> str:
    """Chunk + translate a whole file; shared by to-fa."""
    if len(content) <= chunk_size:
        print(f"[INFO] Content fits in single request ({len(content)} chars)")
        print("[INFO] Translating...")
        return translate_with_retry(
            content, source=source, target=target, retries=retries
        )

    chunks = chunk_by_markers(content, chunk_size)
    total = len(chunks)
    print(f"[INFO] Content split into {total} chunks")
    print(f"[INFO] Chunk sizes: {[len(c) for c in chunks]}")

    results: list[str] = []
    progress = tqdm(total=total, desc="Translating", unit="chunk")
    try:
        for i, chunk in enumerate(chunks):
            print(f"\n[INFO] Translating chunk {i + 1}/{total} ({len(chunk)} chars)...")
            try:
                results.append(
                    translate_with_retry(
                        chunk, source=source, target=target, retries=retries
                    )
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] Failed to translate chunk {i + 1}: {exc}")
                results.append(chunk)  # keep original on failure
            finally:
                progress.update(1)
    finally:
        progress.close()

    return "".join(results)


def cmd_lines_to_en(args: argparse.Namespace) -> int:
    """
    Equivalent to ``transfa.py``.

    Translate every Farsi line of a single file into English, writing
    ``<stem>_<output_suffix><suffix>`` with lines of the form
    ``original = translation``.
    """
    src = Path(args.input)
    if not src.exists():
        logger.error(f"File not found: {src}")
        return 1

    try:
        lines = src.read_text(encoding=args.encoding).splitlines()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error reading file: {exc}")
        return 1

    dst = derive_output_path(src, args.output_suffix)
    print(f"Translating {len(lines)} lines from {src.name}...")

    results: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_worker_line_to_en, line): line for line in lines}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                orig, trans = res
                print(f"{orig} -> {trans}")
                results.append(res)

    try:
        with dst.open("w", encoding="utf-8") as fh:
            for orig, trans in results:
                fh.write(f"{orig} = {trans}\n")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error writing output file: {exc}")
        return 1

    print(f"✓ Translated output saved to {dst}")
    return 0


def cmd_inplace_to_en(args: argparse.Namespace) -> int:
    """
    Equivalent to ``transfa2.py``.

    Recursively translate Farsi content in every supported file under *path*,
    overwriting the originals in place.
    """
    root = Path(args.path)
    if not root.exists():
        logger.error(f"Path does not exist: {root}")
        return 1

    files = collect_files(root, args.suffixes, args.exclude)
    if not files:
        print("No files found to process.")
        return 0

    print(f"Processing {len(files)} files...")
    for path in files:
        _inplace_translate_one(
            path,
            workers=args.workers,
            chunk_size=args.chunk_size,
            sleep=args.sleep,
            final_sleep=args.final_sleep,
        )
    return 0


def _inplace_translate_one(
    path: Path,
    workers: int,
    chunk_size: int,
    sleep: float,
    final_sleep: float,
) -> None:
    """Translate a single file in place using a Pool of chunk workers."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Skipping unreadable file {path}: {exc}")
        return

    if not contains_farsi(content):
        return

    print(f"Translating: {path.name}")
    chunks = chunk_by_regex(content, chunk_size)

    translated_chunks: list[str] = []
    with Pool(processes=workers) as pool:
        async_results = [
            pool.apply_async(_worker_chunk_to_en, ((c, sleep),)) for c in chunks
        ]
        for ar in async_results:
            translated_chunks.append(ar.get())

    new_content = "".join(translated_chunks)
    try:
        path.write_text(new_content, encoding="utf-8")
        print(f"✓ Updated: {path.name}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error writing to {path}: {exc}")

    time.sleep(final_sleep)


def cmd_batch_json(args: argparse.Namespace) -> int:
    """
    Equivalent to ``transfamp.py``.

    Translate every ``*.txt`` file in *directory* into a JSON mapping saved
    under *out_dir* as ``<stem>_translations.json``.
    """
    directory = Path(args.directory)
    files = sorted(directory.glob(args.glob))
    if not files:
        logger.error(f"❌ No files matching {args.glob!r} found in {directory}")
        return 1

    print(f"📚 Found {len(files)} file(s) to translate")
    print(f"🚀 Starting translation with {args.workers} parallel workers")
    print("-" * 40)

    start = time.time()
    ok = 0
    fail = 0

    with Pool(processes=args.workers) as pool:
        async_results = [pool.apply_async(_worker_file_to_dict, (f,)) for f in files]
        for path, ar in zip(files, async_results):
            try:
                src, mapping = ar.get()
                if mapping:
                    _save_translations(src, mapping, args.out_dir)
                    ok += 1
                else:
                    fail += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(f"❌ Failed to process {path.name}: {exc}")
                fail += 1

    elapsed = time.time() - start
    print("=" * 40)
    print("✨ Translation complete!")
    print(f"   ✅ Successful: {ok} files")
    if fail:
        logger.warning(f"   ❌ Failed: {fail} files")
    print(f"   ⏱️  Time elapsed: {elapsed:.2f} seconds")
    print(f"   📁 Output directory: {Path(args.out_dir).absolute()}")
    return 0


def _save_translations(
    src: Path,
    mapping: dict[str, str],
    out_dir: str,
) -> Path:
    """Write a {orig: trans} mapping as JSON under *out_dir*."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{src.stem}_translations.json"
    target.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"💾 Saved: {target.name}")
    return target


# ===========================================================================
# CLI
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translator.py",
        description="Unified translation toolkit (merged tofa/transfa/transfa2/transfamp).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Subcommand → original script:\n"
            "  to-fa         -> tofa.py\n"
            "  lines-to-en   -> transfa.py\n"
            "  inplace-to-en -> transfa2.py\n"
            "  batch-json    -> transfamp.py\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- to-fa (tofa.py) --------------------------------------------------
    p = sub.add_parser(
        "to-fa",
        help="Translate a single file to Farsi (auto-detect source by default).",
    )
    p.add_argument("input", help="Input file")
    p.add_argument(
        "source",
        nargs="?",
        default="auto",
        help="Source language code (default: 'auto').",
    )
    p.add_argument("--target", default="fa", help="Target language (default: fa)")
    p.add_argument(
        "--output-suffix",
        default="fa",
        help="Suffix appended to the stem of the output file (default: fa).",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Max chars per request (default: 5000, as in tofa.py).",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Translation retries per chunk (default: 3).",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output if it already exists (default: skip).",
    )
    p.set_defaults(func=cmd_to_fa)

    # ---- lines-to-en (transfa.py) ----------------------------------------
    p = sub.add_parser(
        "lines-to-en",
        help="Translate Farsi lines of one file into English (line-by-line).",
    )
    p.add_argument("input", help="Input file (utf-8)")
    p.add_argument(
        "--output-suffix",
        default="en",
        help="Suffix for the output file (default: en).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="ProcessPoolExecutor workers (default: 4).",
    )
    p.add_argument(
        "--encoding", default="utf-8", help="Input encoding (default: utf-8)."
    )
    p.set_defaults(func=cmd_lines_to_en)

    # ---- inplace-to-en (transfa2.py) -------------------------------------
    p = sub.add_parser(
        "inplace-to-en",
        help="Recursively translate Farsi files into English, in place.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Root directory to walk (default: current dir).",
    )
    p.add_argument(
        "--workers", type=int, default=8, help="Pool workers per file (default: 8)."
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=4900,
        help="Max chunk chars (default: 4900, as in transfa2.py).",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="Sleep seconds after each translated chunk (default: 1.5).",
    )
    p.add_argument(
        "--final-sleep",
        type=float,
        default=2.0,
        help="Sleep seconds after finishing each file (default: 2.0).",
    )
    p.add_argument(
        "--suffixes",
        nargs="+",
        default=list(DEFAULT_SUFFIXES),
        help="File suffixes to process.",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=list(DEFAULT_EXCLUDES),
        help="Directory names to skip.",
    )
    p.set_defaults(func=cmd_inplace_to_en)

    # ---- batch-json (transfamp.py) ---------------------------------------
    p = sub.add_parser(
        "batch-json",
        help="Translate every *.txt in a directory into per-file JSON maps.",
    )
    p.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing the .txt files (default: current dir).",
    )
    p.add_argument("--workers", type=int, default=8, help="Pool workers (default: 8).")
    p.add_argument(
        "--glob", default="*.txt", help="Glob pattern for input files (default: *.txt)."
    )
    p.add_argument(
        "--out-dir",
        default="./translations",
        help="Directory where the *_translations.json files go.",
    )
    p.set_defaults(func=cmd_batch_json)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
