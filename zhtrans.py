#!/data/data/com.termux/files/home/.local/bin/python
"""
merged_translate.py — unified Chinese→English translation utility.

This single file replaces four scripts that overlapped heavily:

    chintrans.py           ->  python merged_translate.py chunked  <input_file>
    transchin.py           ->  python merged_translate.py line     <input_file>
    dtransline_chinese.py  ->  python merged_translate.py walk     [paths ...]
    tchin.py               ->  python merged_translate.py whole    <input_path>

Common behaviour (line-oriented translation via Google Translate) is
factored into shared helpers; each subcommand preserves its original
script's distinctive logic.

Third-party dependencies (install before running):

    pip install deep-translator loguru

Examples
--------
    # Translate a single file in place, batching lines into ≤5000-char chunks.
    python merged_translate.py chunked input.txt

    # Same, but one API call per line, 4 worker processes.
    python merged_translate.py line input.txt --workers 4

    # Walk a tree and translate every Chinese line in place (dry-run first).
    python merged_translate.py walk ./docs --dry-run
    python merged_translate.py walk ./docs -e .py .md --workers 8

    # Whole-file translation to `input_eng.txt` with auto language detection.
    python merged_translate.py whole input.txt --lang auto

Assumptions / deviations from originals (documented so nothing is silent):
  * tchin.py's chunker had a bug (`range(0, len, 32768)` with chunks of 4500);
    fixed to `range(0, len, chunk_size)`. Otherwise long texts silently lost
    content. Controlled via `--chunk-size`.
  * dtransline_chinese.py printed `threshold*40`; corrected to `threshold*100`
    (purely cosmetic).
  * logging is unified on loguru, which was already a dependency of two of the
    four scripts.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from deep_translator import GoogleTranslator, single_detection
from loguru import logger


# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

# Matches CJK ideographs (BMP + extensions B–F) and compatibility ideographs.
# Union of the regexes used by the original scripts.
CHINESE_RE = re.compile(
    "[\u4e00-\u9fff"  # CJK Unified Ideographs
    "\u3400-\u4dbf"  # Extension A
    "\U00020000-\U0002a6df"  # Extension B
    "\U0002a700-\U0002b73f"  # Extension C
    "\U0002b740-\U0002b81f"  # Extension D
    "\U0002b820-\U0002ceaf"  # Extension E/F
    "\uf900-\ufaff]"  # Compatibility Ideographs
)

DEFAULT_EXTENSIONS = (
    ".txt",
    ".md",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".csv",
)


# --------------------------------------------------------------------------- #
# Shared helpers                                                               #
# --------------------------------------------------------------------------- #


def has_chinese(text: str) -> bool:
    """True if `text` contains at least one CJK character."""
    return bool(CHINESE_RE.search(text))


def chinese_ratio(text: str) -> float:
    """Fraction of non-whitespace characters that are CJK."""
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(CHINESE_RE.findall(stripped)) / len(stripped)


def meets_threshold(text: str, threshold: float) -> bool:
    """True if `text`'s CJK ratio is >= `threshold`.

    `threshold == 0.0` collapses to the 'any Chinese char' check used by
    chintrans.py / transchin.py.
    """
    return chinese_ratio(text) >= threshold


def build_translator(source: str = "auto", target: str = "en") -> GoogleTranslator:
    """Construct a GoogleTranslator."""
    return GoogleTranslator(source=source, target=target)


def translate_with_retries(
    translator: GoogleTranslator,
    text: str,
    retries: int,
    retry_delay: float,
    success_delay: float = 0.0,
) -> Optional[str]:
    """Translate `text`, retrying up to `retries` times.

    Returns the translated string, or ``None`` if all attempts failed.
    `success_delay` sleeps only after a successful call (rate limiting).
    """
    for attempt in range(retries):
        try:
            result = translator.translate(text)
            if result:
                if success_delay:
                    time.sleep(success_delay)
                return result
        except Exception as exc:  # noqa: BLE001 - we want to log anything
            logger.warning(
                "Translation failed (attempt {}/{}): {}",
                attempt + 1,
                retries,
                exc,
            )
            if attempt < retries - 1 and retry_delay:
                time.sleep(retry_delay)
    return None


def chunk_lines(lines: Sequence[str], max_chars: int) -> List[List[str]]:
    """Group `lines` into chunks of total size (len+1 per line) <= max_chars.

    A line longer than `max_chars` gets its own chunk. Mirrors the algorithm
    from chintrans.py so line counts stay aligned with the translation output.
    """
    chunks: List[List[str]] = []
    current: List[str] = []
    total = 0
    for line in lines:
        size = len(line) + 1
        if total + size > max_chars and current:
            chunks.append(current)
            current, total = [], 0
        if size > max_chars:
            if current:
                chunks.append(current)
                current, total = [], 0
            chunks.append([line])
        else:
            current.append(line)
            total += size
    if current:
        chunks.append(current)
    return chunks


def read_stripped_lines(path: Path) -> List[str]:
    """Read non-empty, stripped lines from `path` (used by chunked/line modes)."""
    with path.open(encoding="utf-8") as fh:
        return [w.strip() for w in fh if w.strip()]


def write_inplace(path: Path, original: Sequence[str], translations: dict) -> None:
    """Rewrite `path` line-by-line, substituting translated lines."""
    with path.open("w", encoding="utf-8") as fh:
        for line in original:
            fh.write(f"{translations.get(line, line)}\n")


# --------------------------------------------------------------------------- #
# Multiprocessing workers (must be top-level for pickling)                     #
# --------------------------------------------------------------------------- #


def _worker_chunked_chunk(task):
    """Worker for the `chunked` subcommand: translate one chunk of lines."""
    chunk, retries, retry_delay, source, target = task
    text = "\n".join(chunk)
    translator = build_translator(source, target)
    result = translate_with_retries(translator, text, retries, retry_delay)
    return chunk, result


def _worker_single_line(task):
    """Worker for the `line` subcommand: translate one line."""
    line, retries, retry_delay, source, target = task
    translator = build_translator(source, target)
    result = translate_with_retries(translator, line, retries, retry_delay)
    return line, result


def _worker_walk_file(task):
    """Worker for the `walk` subcommand: translate a whole file in place."""
    (
        file_path,
        dry_run,
        threshold,
        source,
        target,
        retries,
        retry_delay,
        success_delay,
    ) = task

    stats = {
        "file": file_path,
        "total_lines": 0,
        "chinese_lines": 0,
        "translated_lines": 0,
        "errors": 0,
    }
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Processing: {file_path}")

    try:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines(keepends=True)
        stats["total_lines"] = len(lines)

        translator = build_translator(source, target)
        out: List[str] = []
        found_any = False

        for line in lines:
            if meets_threshold(line, threshold):
                stats["chinese_lines"] += 1
                found_any = True
                if dry_run:
                    out.append(line)
                    continue

                # Preserve leading indentation and trailing newline/whitespace.
                leading = line[: len(line) - len(line.lstrip())]
                trailing = line[len(line.rstrip()) :]
                translated = translate_with_retries(
                    translator,
                    line.strip(),
                    retries,
                    retry_delay,
                    success_delay,
                )
                out.append(f"{leading}{translated or line.strip()}{trailing}")
                stats["translated_lines"] += 1
                if stats["translated_lines"] % 10 == 0:
                    print(f"  Progress: {stats['translated_lines']} lines translated")
            else:
                out.append(line)

        if dry_run and found_any:
            print(f"  i Found {stats['chinese_lines']} lines with Chinese text")
        elif dry_run:
            print("  No Chinese text found, skipping.")
        elif found_any:
            path.write_text("".join(out), encoding="utf-8")
            print(f"  Completed: {stats['translated_lines']} lines translated")
        else:
            print("  No Chinese text found, skipping.")

    except Exception as exc:  # noqa: BLE001
        logger.error(f"  Error processing {file_path}: {exc}")
        stats["errors"] += 1

    return stats


# --------------------------------------------------------------------------- #
# Subcommand: chunked  (was chintrans.py)                                      #
# --------------------------------------------------------------------------- #


def cmd_chunked(args: argparse.Namespace) -> int:
    """Translate a single file in place, batching lines into chunks."""
    input_path = Path(args.input_file.strip())
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path.name)
        return 1

    try:
        lines = read_stripped_lines(input_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error reading input file: {}", exc)
        return 1

    if not lines:
        print(f"No lines found in {input_path.name}")
        return 0

    chinese_lines = [ln for ln in lines if has_chinese(ln)]
    non_chinese = [ln for ln in lines if not has_chinese(ln)]
    print(
        f"Loaded {len(lines)} lines: {len(chinese_lines)} with Chinese, "
        f"{len(non_chinese)} already English/skipped"
    )

    if not chinese_lines:
        print(f"No Chinese lines to translate in {input_path.name}")
        return 0

    chunks = chunk_lines(chinese_lines, args.chunk_size)
    print(
        f"Created {len(chunks)} chunks from {len(chinese_lines)} Chinese lines "
        f"(max {args.chunk_size} chars per chunk)"
    )

    tasks = [
        (chunk, args.retries, args.retry_delay, args.source, args.target)
        for chunk in chunks
    ]
    translations: dict = {}

    with Pool(processes=args.workers) as pool:
        results = [pool.apply_async(_worker_chunked_chunk, (t,)) for t in tasks]
        for async_res, chunk in zip(results, chunks):
            try:
                lines_out, translated = async_res.get()
                if translated:
                    translated_lines = translated.split("\n")
                    for i, original in enumerate(lines_out):
                        if i < len(translated_lines):
                            translations[original] = translated_lines[i]
                            print(f"{original} -> {translated_lines[i]}")
                        else:
                            logger.error(
                                "Line count mismatch in chunk, missing "
                                "translation for: {}",
                                original,
                            )
                else:
                    logger.error(
                        "Failed to translate chunk starting with: {}",
                        chunk[0][:50],
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unexpected error for chunk starting with '{}': {}",
                    chunk[0][:50],
                    exc,
                )

    try:
        write_inplace(input_path, lines, translations)
        print(
            f"Updated {input_path.name}: translated {len(translations)} lines, "
            f"kept {len(non_chinese)} lines unchanged"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error updating input file: {}", exc)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: line  (was transchin.py)                                         #
# --------------------------------------------------------------------------- #


def cmd_line(args: argparse.Namespace) -> int:
    """Translate a single file in place, one line per API call."""
    input_path = Path(args.input_file.strip())
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path.name)
        return 1

    try:
        lines = read_stripped_lines(input_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error reading input file: {}", exc)
        return 1

    if not lines:
        print(f"No lines found in {input_path.name}")
        return 0

    chinese_lines = [ln for ln in lines if has_chinese(ln)]
    non_chinese = [ln for ln in lines if not has_chinese(ln)]
    print(
        f"Loaded {len(lines)} lines: {len(chinese_lines)} with Chinese, "
        f"{len(non_chinese)} already English/skipped"
    )

    if not chinese_lines:
        print(f"No Chinese lines to translate in {input_path.name}")
        return 0

    print(f"Starting translation with {args.workers} workers...")
    translations: dict = {}

    tasks = [
        (ln, args.retries, args.retry_delay, args.source, args.target)
        for ln in chinese_lines
    ]
    with Pool(processes=args.workers) as pool:
        results = [pool.apply_async(_worker_single_line, (t,)) for t in tasks]
        for original, async_res in zip(chinese_lines, results):
            try:
                _, translated = async_res.get()
                if translated:
                    translations[original] = translated
                    print(f"{original} -> {translated}")
                else:
                    logger.error("Could not translate: {}", original)
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error for '{}': {}", original, exc)

    try:
        write_inplace(input_path, lines, translations)
        print(
            f"Updated {input_path.name}: translated {len(translations)} lines, "
            f"kept {len(non_chinese)} lines unchanged"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error updating input file: {}", exc)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: walk  (was dtransline_chinese.py)                                #
# --------------------------------------------------------------------------- #


def _collect_walk_files(
    paths: Sequence[str],
    extensions: Sequence[str],
    excludes: Iterable[str],
) -> List[Path]:
    """Expand file/dir arguments into a flat list of file paths to process."""
    exclude_set = {Path(p).resolve() for p in excludes}
    found: List[Path] = []

    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.resolve() not in exclude_set:
                found.append(p)
        elif p.is_dir():
            for ext in extensions:
                for candidate in p.rglob(f"*{ext}"):
                    if (
                        candidate.is_file()
                        and candidate.resolve() not in exclude_set
                        and not any(part.startswith(".") for part in candidate.parts)
                    ):
                        found.append(candidate)
    return found


def cmd_walk(args: argparse.Namespace) -> int:
    """Walk files/directories, translating Chinese lines in place."""
    files = _collect_walk_files(args.paths, args.extensions, args.exclude)
    if not files:
        print("No files to process.")
        return 0

    print(
        f"Found {len(files)} files. Using {args.workers} workers "
        f"(Threshold: {args.threshold * 100:.0f}%)"
    )

    tasks = [
        (
            str(p),
            args.dry_run,
            args.threshold,
            args.source,
            args.target,
            args.retries,
            args.retry_delay,
            args.success_delay,
        )
        for p in files
    ]

    if args.workers == 1:
        results = [_worker_walk_file(t) for t in tasks]
    else:
        with Pool(processes=args.workers) as pool:
            results = pool.map(_worker_walk_file, tasks)

    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Files processed:    {len(results)}")
    print(f"Chinese lines:      {sum(r['chinese_lines'] for r in results):,}")
    if not args.dry_run:
        print(f"Translated lines:   {sum(r['translated_lines'] for r in results):,}")
    print(f"Errors:             {sum(r['errors'] for r in results)}")
    print("-" * 40)
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: whole  (was tchin.py)                                            #
# --------------------------------------------------------------------------- #


def _translate_long_text(
    text: str, translator: GoogleTranslator, chunk_size: int
) -> str:
    """Translate `text` in chunks of `chunk_size` chars and concatenate."""
    if not text:
        return ""
    parts = [
        translator.translate(text[i : i + chunk_size]) or ""
        for i in range(0, len(text), chunk_size)
    ]
    return "".join(parts)


def _translate_python_source(
    text: str, translator: GoogleTranslator, chunk_size: int
) -> str:
    """.py-aware translation: handles triple-quoted docstrings and # comments."""
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    in_doc = False
    delim: Optional[str] = None

    for line in lines:
        stripped = line.strip()

        # Start of a triple-quoted string at the beginning of a line.
        if not in_doc and stripped.startswith(('"""', "'''")):
            in_doc = True
            delim = stripped[:3]
            inner = stripped[3:]
            if inner.endswith(delim):
                content = inner[:-3]
                translated = _translate_long_text(content, translator, chunk_size)
                out.append(line.replace(content, translated))
                in_doc, delim = False, None
            else:
                translated = _translate_long_text(inner, translator, chunk_size)
                out.append(line.replace(inner, translated))
            continue

        if in_doc:
            if stripped.endswith(delim):
                content = line.replace(delim, "")
                translated = _translate_long_text(content, translator, chunk_size)
                out.append(f"{translated}{delim}\n")
                in_doc, delim = False, None
            else:
                out.append(_translate_long_text(line, translator, chunk_size))
            continue

        # Inline # comment.
        if "#" in line:
            code, comment = line.split("#", 1)
            translated = _translate_long_text(comment, translator, chunk_size)
            out.append(f"{code}# {translated}\n")
        else:
            out.append(line)

    return "".join(out)


def cmd_whole(args: argparse.Namespace) -> int:
    """Translate an entire file, writing to `<stem>_eng<suffix>`."""
    input_path = Path(args.input_path)
    if not input_path.exists():
        print("File not found.", file=sys.stderr)
        return 1

    text = input_path.read_text(encoding="utf-8")
    suffix = input_path.suffix.lower()

    # Language detection / selection
    source_lang = args.lang
    if source_lang == "auto":
        try:
            source_lang = single_detection(text[:500])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Language auto-detection failed ({}); using zh-CN", exc)
            source_lang = "zh-CN"

    translator = build_translator(source_lang, args.target)

    # Decide whether to apply .py-aware handling.
    if args.code_mode == "auto":
        use_code_mode = suffix == ".py"
    else:
        use_code_mode = args.code_mode == "on"

    if use_code_mode:
        translated = _translate_python_source(text, translator, args.chunk_size)
    else:
        translated = _translate_long_text(text, translator, args.chunk_size)

    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name(f"{input_path.stem}_eng{input_path.suffix}")
    )
    output_path.write_text(translated, encoding="utf-8")
    print(f"Translated ({source_lang} -> {args.target}): {output_path}")
    return 0


# --------------------------------------------------------------------------- #
# Argument parser                                                              #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merged_translate.py",
        description="Unified Chinese->English translation utility "
        "(merges chintrans.py, transchin.py, "
        "dtransline_chinese.py, tchin.py).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original script mapping:\n"
            "  chintrans.py           ->  chunked <input_file>\n"
            "  transchin.py           ->  line    <input_file>\n"
            "  dtransline_chinese.py  ->  walk    [paths ...]\n"
            "  tchin.py               ->  whole   <input_path>\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- chunked -----------------------------------------------------------
    p = sub.add_parser(
        "chunked",
        help="In-place translate; batch lines into <=N-char chunks (was chintrans.py).",
    )
    p.add_argument("input_file", help="File to translate in place.")
    p.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Max characters per chunk (default: 5000).",
    )
    p.add_argument(
        "--workers", "-w", type=int, default=8, help="Worker processes (default: 8)."
    )
    p.add_argument(
        "--retries", type=int, default=3, help="Retry attempts per chunk (default: 3)."
    )
    p.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5).",
    )
    p.add_argument("--source", default="auto", help="Source language (default: auto).")
    p.add_argument("--target", default="en", help="Target language (default: en).")
    p.set_defaults(func=cmd_chunked)

    # ---- line --------------------------------------------------------------
    p = sub.add_parser(
        "line",
        help="In-place translate one line per API call (was transchin.py).",
    )
    p.add_argument("input_file", help="File to translate in place.")
    p.add_argument(
        "--workers", "-w", type=int, default=8, help="Worker processes (default: 8)."
    )
    p.add_argument(
        "--retries", type=int, default=3, help="Retry attempts per line (default: 3)."
    )
    p.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Seconds between retries (default: 0.5).",
    )
    p.add_argument("--source", default="auto", help="Source language (default: auto).")
    p.add_argument("--target", default="en", help="Target language (default: en).")
    p.set_defaults(func=cmd_line)

    # ---- walk --------------------------------------------------------------
    p = sub.add_parser(
        "walk",
        help="Walk files/directories and translate Chinese lines in place "
        "(was dtransline_chinese.py).",
    )
    p.add_argument("paths", nargs="+", help="Files or directories to process.")
    p.add_argument(
        "--extensions",
        "-e",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to process when walking directories.",
    )
    p.add_argument(
        "--workers",
        "-w",
        type=int,
        default=cpu_count(),
        help=f"Worker processes (default: {cpu_count()}).",
    )
    p.add_argument("--exclude", "-x", nargs="+", default=[], help="Paths to exclude.")
    p.add_argument(
        "--dry-run",
        "-d",
        action="store_true",
        help="Detect Chinese lines only; do not translate or write.",
    )
    p.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=0.3,
        help="Minimum CJK ratio for a line to be translated (default: 0.3).",
    )
    p.add_argument(
        "--retries", type=int, default=3, help="Retry attempts per line (default: 3)."
    )
    p.add_argument(
        "--retry-delay",
        type=float,
        default=1.5,
        help="Base retry delay in seconds; multiplied by attempt "
        "number (default: 1.5).",
    )
    p.add_argument(
        "--success-delay",
        type=float,
        default=0.05,
        help="Sleep after each successful translation (rate limit; default: 0.05).",
    )
    p.add_argument("--source", default="auto", help="Source language (default: auto).")
    p.add_argument("--target", default="en", help="Target language (default: en).")
    p.set_defaults(func=cmd_walk)

    # ---- whole -------------------------------------------------------------
    p = sub.add_parser(
        "whole",
        help="Translate an entire file to <stem>_eng<suffix> (was tchin.py).",
    )
    p.add_argument("input_path", help="File to translate.")
    p.add_argument(
        "--lang",
        default="zh-CN",
        help="Source language, or 'auto' for detection (default: zh-CN).",
    )
    p.add_argument("--target", default="en", help="Target language (default: en).")
    p.add_argument(
        "--chunk-size",
        type=int,
        default=4500,
        help="Characters per translation call (default: 4500).",
    )
    p.add_argument(
        "--output", default=None, help="Output path (default: <stem>_eng<suffix>)."
    )
    p.add_argument(
        "--code-mode",
        choices=("auto", "on", "off"),
        default="auto",
        help=".py-aware docstring/comment handling: "
        "'auto' enables it for *.py files (default).",
    )
    p.set_defaults(func=cmd_whole)

    return parser


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
