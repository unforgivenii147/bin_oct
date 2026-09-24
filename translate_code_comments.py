#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate comments, docstrings, print strings, and optionally arbitrary files.

This script merges the behavior of five related scripts:

    pytrans.py       -> python merged_translator.py scan [OPTIONS]
    pytranslator.py  -> python merged_translator.py detect [OPTIONS]
    trans_py.py      -> python merged_translator.py ast [OPTIONS]
    transjap.py      -> python merged_translator.py japanese [OPTIONS]
    ultralinetrans.py -> python merged_translator.py batch [OPTIONS]

Third-party dependencies:

    pip install deep-translator pycld2 langdetect

Examples:

    # Translate comments, print strings, and docstrings using pycld2.
    python merged_translator.py scan .

    # Use langdetect and process files with all available CPU workers.
    python merged_translator.py detect . --workers 4

    # Translate comments and docstrings, creating .bak files.
    python merged_translator.py ast . --backup

    # Translate Japanese comments and docstrings.
    python merged_translator.py japanese .

    # Translate Python and non-Python files using batch translation.
    python merged_translator.py batch .

    # Process explicit files in batch mode.
    python merged_translator.py batch README.md src/example.py
"""

from __future__ import annotations

import argparse
import ast
import io
import logging
import os
import re
import shutil
import sys
import tokenize
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from deep_translator import GoogleTranslator


LOGGER = logging.getLogger("merged_translator")

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        "lazy",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
    }
)

DEFAULT_MARKERS = frozenset(
    {
        "TODO",
        "FIXME",
        "HACK",
        "XXX",
        "NOTE",
        "BUG",
        "PYLINT",
        "NOQA",
        "TYPE:IGNORE",
        "PRAGMA",
        "CODING:",
        "ENCODING:",
        "CHARSET:",
        "DRYRUN",
        "DRY-RUN",
        "RESCURSIVE MODE ENABLED",
        ".GITIGNORE",
    }
)

JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")
PYCLD2_CODES_TO_SKIP = {"en", "un"}


@dataclass(frozen=True)
class TranslationConfig:
    """Configuration shared by all translation modes."""

    target_language: str = "en"
    source_language: str = "auto"
    delay: float = 0.5
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS
    markers: frozenset[str] = DEFAULT_MARKERS
    dry_run: bool = False
    backup: bool = False
    max_chars: int | None = None


@dataclass
class TranslationStats:
    """Counters collected while processing one or more files."""

    changed_files: int = 0
    translated_items: int = 0
    failed_items: int = 0


class Translator:
    """Small wrapper around deep-translator with consistent error handling."""

    def __init__(self, config: TranslationConfig) -> None:
        self.config = config

    def translate(self, text: str) -> str:
        """Translate text, returning the original text if translation fails."""
        if not text.strip():
            return text

        if self.config.max_chars is not None and len(text) > self.config.max_chars:
            return text

        try:
            result = GoogleTranslator(
                source=self.config.source_language,
                target=self.config.target_language,
            ).translate(text)

            if self.config.delay > 0:
                import time

                time.sleep(self.config.delay)

            return result or text
        except Exception as exc:  # third-party library exceptions vary
            LOGGER.warning("Translation failed for %r: %s", text[:80], exc)
            return text

    def translate_many(self, texts: Sequence[str]) -> list[str]:
        """Translate a sequence as one batch where possible.

        Batch mode falls back to individual translations if the provider
        returns an unexpected number of segments.
        """
        if not texts:
            return []

        separator = "\n===|||===\n"
        combined = separator.join(texts)

        try:
            result = GoogleTranslator(
                source=self.config.source_language,
                target=self.config.target_language,
            ).translate(combined)

            if not result:
                return list(texts)

            translated = [part.strip() for part in result.split(separator)]
            if len(translated) == len(texts):
                return translated

            LOGGER.warning(
                "Batch translation count mismatch: got %d, expected %d; "
                "falling back to individual translation",
                len(translated),
                len(texts),
            )
        except Exception as exc:
            LOGGER.warning("Batch translation failed: %s", exc)

        return [self.translate(text) for text in texts]


def contains_non_ascii(text: str) -> bool:
    """Return whether text contains at least one non-ASCII character."""
    return bool(NON_ASCII_RE.search(text))


def contains_japanese(text: str) -> bool:
    """Return whether text contains Japanese Hiragana, Katakana, or Kanji."""
    return bool(JAPANESE_RE.search(text))


def contains_non_latin(text: str) -> bool:
    """Return whether text contains alphabetic characters outside Latin."""
    return any(character.isalpha() and not character.isascii() for character in text)


def is_ignored_text(
    text: str,
    config: TranslationConfig,
    *,
    conservative: bool,
) -> bool:
    """Apply the marker and trivial-text filters used by the scan modes."""
    stripped = text.strip()

    if not stripped:
        return True

    if stripped.startswith("#!") or stripped.startswith("#"):
        return True

    upper = stripped.upper()
    if any(marker in upper for marker in config.markers):
        return True

    if not any(character.isalpha() for character in stripped):
        return True

    if conservative:
        if stripped.isascii() and (len(stripped.split()) <= 2 and len(stripped) < 30):
            return True

    return False


def should_translate_pycld2(
    text: str,
    config: TranslationConfig,
) -> bool:
    """Use pycld2 to determine whether text is probably non-English."""
    if is_ignored_text(text, config, conservative=True):
        return False

    try:
        import pycld2

        _, _, details = pycld2.detect(text.strip())
        language_code = details[0][1]
        return language_code not in PYCLD2_CODES_TO_SKIP
    except Exception as exc:
        LOGGER.warning("pycld2 detection failed: %s", exc)
        return False


def should_translate_langdetect(
    text: str,
    config: TranslationConfig,
) -> bool:
    """Use langdetect plus non-Latin detection."""
    if is_ignored_text(text, config, conservative=False):
        return False

    if contains_non_latin(text):
        return True

    try:
        from langdetect import detect

        return detect(text.strip()) != config.target_language
    except Exception:
        return contains_non_latin(text)


def should_translate_japanese(
    text: str,
    config: TranslationConfig,
) -> bool:
    """Return true only for Japanese-containing text."""
    if is_ignored_text(text, config, conservative=False):
        return False

    return contains_japanese(text)


def should_translate_non_ascii(
    text: str,
    config: TranslationConfig,
) -> bool:
    """Return true for non-ASCII text not excluded by markers."""
    if is_ignored_text(text, config, conservative=False):
        return False

    return contains_non_ascii(text)


def iter_python_files(
    root: Path,
    excluded_dirs: frozenset[str],
) -> Iterator[Path]:
    """Yield Python files while skipping configured directory names."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return

    for path in root.rglob("*.py"):
        if not any(part in excluded_dirs for part in path.parts):
            yield path


def iter_all_files(
    root: Path,
    excluded_dirs: frozenset[str],
) -> Iterator[Path]:
    """Yield files recursively while skipping configured directories."""
    if root.is_file():
        yield root
        return

    for path in root.rglob("*"):
        if path.is_file() and not any(part in excluded_dirs for part in path.parts):
            yield path


def line_offsets(source: str) -> list[int]:
    """Return absolute offsets for the beginning of every source line."""
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def absolute_offset(
    offsets: Sequence[int],
    line: int,
    column: int,
) -> int:
    """Convert a one-based line and zero-based column to an offset."""
    return offsets[line - 1] + column


def literal_parts(token_text: str) -> tuple[str, str, str]:
    """Split a Python string token into prefix, quote, and suffix.

    The returned suffix is the same quote delimiter as the quote. This
    supports ordinary and triple-quoted strings with common prefixes.
    """
    match = re.match(
        r"(?P<prefix>[rRuUbBfF]*)(?P<quote>'''|\"\"\"|'|\")",
        token_text,
    )
    if not match:
        raise ValueError(f"Unsupported string token: {token_text!r}")

    prefix = match.group("prefix")
    quote = match.group("quote")
    return prefix, quote, quote


def encode_literal(value: str, original_token: str) -> str:
    """Encode translated text using the original token's quote style."""
    prefix, quote, closing_quote = literal_parts(original_token)

    if "f" in prefix.lower():
        # Replacing f-string expressions safely requires a full f-string
        # parser. Preserve such strings rather than corrupting expressions.
        raise ValueError("Formatted string literals are not rewritten")

    if "r" in prefix.lower():
        escaped = value.replace("\\", "\\\\")
    else:
        escaped = value.replace("\\", "\\\\")
        escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
        escaped = escaped.replace("\t", "\\t")

    escaped = escaped.replace(closing_quote, "\\" + closing_quote)
    return f"{prefix}{quote}{escaped}{quote}"


def ast_string_locations(
    tree: ast.AST,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Return print-string and docstring token start locations."""
    print_locations: set[tuple[int, int]] = set()
    docstring_locations: set[tuple[int, int]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(
                        argument.value, str
                    ):
                        print_locations.add((argument.lineno, argument.col_offset))

        if isinstance(
            node,
            (
                ast.Module,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            body = getattr(node, "body", [])
            if not body:
                continue

            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_locations.add((first.value.lineno, first.value.col_offset))

    return print_locations, docstring_locations


def replace_token_text(
    source: str,
    replacements: Sequence[tuple[int, int, str]],
) -> str:
    """Apply absolute source replacements from right to left."""
    result = source

    for start, end, replacement in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        result = result[:start] + replacement + result[end:]

    return result


def translate_python_tokens(
    source: str,
    translator: Translator,
    predicate,
    *,
    include_print_strings: bool,
    include_docstrings: bool,
    include_comments: bool,
    batch: bool = False,
) -> tuple[str, int]:
    """Translate selected comments and string literals in Python source."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        tree = ast.parse(source)
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        LOGGER.warning("Skipping Python source with parse error: %s", exc)
        return source, 0

    offsets = line_offsets(source)
    print_locations, docstring_locations = ast_string_locations(tree)
    candidates: list[tuple[int, int, str, str]] = []

    for token in tokens:
        start = absolute_offset(offsets, *token.start)
        end = absolute_offset(offsets, *token.end)

        if token.type == tokenize.COMMENT and include_comments:
            text = token.string.lstrip("#").strip()
            if predicate(text):
                candidates.append((start, end, text, "comment"))

        elif token.type == tokenize.STRING:
            location = (token.start[0], token.start[1])
            is_print = location in print_locations
            is_docstring = location in docstring_locations

            if (is_print and include_print_strings) or (
                is_docstring and include_docstrings
            ):
                try:
                    value = ast.literal_eval(token.string)
                except (SyntaxError, ValueError):
                    continue

                if isinstance(value, str) and predicate(value):
                    kind = "docstring" if is_docstring else "print-string"
                    candidates.append((start, end, value, kind))

    if not candidates:
        return source, 0

    texts = [candidate[2] for candidate in candidates]
    translated = (
        translator.translate_many(texts)
        if batch
        else [translator.translate(text) for text in texts]
    )

    replacements: list[tuple[int, int, str]] = []
    changed = 0

    for candidate, translated_text in zip(
        candidates,
        translated,
        strict=False,
    ):
        start, end, original_text, kind = candidate

        if translated_text == original_text:
            continue

        try:
            if kind == "comment":
                replacement = "# " + translated_text
            else:
                original_token = source[start:end]
                replacement = encode_literal(
                    translated_text,
                    original_token,
                )
        except ValueError as exc:
            LOGGER.warning("Skipping literal at offset %d: %s", start, exc)
            continue

        LOGGER.info(
            "  [%s] %s -> %s",
            kind,
            original_text,
            translated_text,
        )
        replacements.append((start, end, replacement))
        changed += 1

    updated = replace_token_text(source, replacements)

    try:
        ast.parse(updated)
    except SyntaxError as exc:
        LOGGER.error("Generated invalid Python; discarding changes: %s", exc)
        return source, 0

    return updated, changed


def translate_ast_mode(
    source: str,
    translator: Translator,
    predicate,
) -> tuple[str, int]:
    """AST-oriented mode corresponding to trans_py.py."""
    return translate_python_tokens(
        source,
        translator,
        predicate,
        include_print_strings=False,
        include_docstrings=True,
        include_comments=True,
        batch=False,
    )


def translate_file(
    path: Path,
    translator: Translator,
    transform,
    *,
    config: TranslationConfig,
) -> tuple[Path, bool, int]:
    """Read, transform, and optionally write one file."""
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        LOGGER.error("Could not read %s: %s", path, exc)
        return path, False, 0

    try:
        updated, count = transform(original)
    except Exception as exc:
        LOGGER.error("Failed to process %s: %s", path, exc)
        return path, False, 0

    if count == 0 or updated == original:
        return path, False, 0

    if config.dry_run:
        LOGGER.info("[dry-run] Would update %s", path)
        return path, True, count

    if config.backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copyfile(path, backup_path)
        except OSError as exc:
            LOGGER.error("Could not create backup %s: %s", backup_path, exc)
            return path, False, 0

    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        LOGGER.error("Could not write %s: %s", path, exc)
        return path, False, 0

    LOGGER.info("[updated] %s", path)
    return path, True, count


def process_in_parallel(
    files: Sequence[Path],
    processor,
    *,
    workers: int,
) -> TranslationStats:
    """Process files concurrently using a bounded thread pool."""
    stats = TranslationStats()

    if not files:
        return stats

    worker_count = max(1, workers)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(processor, path) for path in files]

        for future in as_completed(futures):
            try:
                _, changed, count = future.result()
                if changed:
                    stats.changed_files += 1
                stats.translated_items += count
            except Exception as exc:
                stats.failed_items += 1
                LOGGER.error("Worker failed: %s", exc)

    return stats


def run_python_mode(
    args: argparse.Namespace,
    *,
    detector,
    include_print_strings: bool,
    include_docstrings: bool,
    include_comments: bool,
    ast_mode: bool = False,
    batch: bool = False,
) -> int:
    """Run one of the Python-source translation modes."""
    excluded = frozenset(args.exclude)
    config = TranslationConfig(
        target_language=args.target,
        source_language=args.source,
        delay=args.delay,
        excluded_dirs=excluded,
        markers=frozenset(marker.upper() for marker in args.marker),
        dry_run=args.dry_run,
        backup=args.backup,
        max_chars=args.max_chars,
    )
    translator = Translator(config)

    root = Path(args.path).resolve()
    files = list(iter_python_files(root, excluded))

    if not files:
        print("No Python files found.")
        return 0

    def process(path: Path):
        def transform(source: str) -> tuple[str, int]:
            if ast_mode:
                return translate_ast_mode(
                    source,
                    translator,
                    detector,
                )

            return translate_python_tokens(
                source,
                translator,
                detector,
                include_print_strings=include_print_strings,
                include_docstrings=include_docstrings,
                include_comments=include_comments,
                batch=batch,
            )

        _, changed, count = translate_file(
            path,
            translator,
            transform,
            config=config,
        )
        return path, changed, count

    print(f"Found {len(files)} Python files. Processing with {args.workers} workers...")
    stats = process_in_parallel(
        files,
        process,
        workers=args.workers,
    )
    print(
        f"Done. Modified {stats.changed_files} files; "
        f"translated {stats.translated_items} items."
    )
    return 0


def translate_plain_text(
    source: str,
    translator: Translator,
    predicate,
    *,
    batch: bool,
) -> tuple[str, int]:
    """Translate arbitrary non-Python text line by line."""
    lines = source.splitlines(keepends=True)
    candidates: list[tuple[int, str, str]] = []

    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if predicate(content):
            candidates.append((index, content, line[len(content) :]))

    if not candidates:
        return source, 0

    texts = [item[1] for item in candidates]
    translated = (
        translator.translate_many(texts)
        if batch
        else [translator.translate(text) for text in texts]
    )

    changed = 0
    for (index, original, newline), replacement in zip(
        candidates,
        translated,
        strict=False,
    ):
        if replacement != original:
            lines[index] = replacement + newline
            changed += 1

    return "".join(lines), changed


def run_batch_mode(args: argparse.Namespace) -> int:
    """Run the ultralinetrans.py-compatible batch mode."""
    excluded = frozenset(args.exclude)
    config = TranslationConfig(
        target_language=args.target,
        source_language=args.source,
        delay=args.delay,
        excluded_dirs=excluded,
        markers=frozenset(marker.upper() for marker in args.marker),
        dry_run=args.dry_run,
        backup=args.backup,
        max_chars=args.max_chars,
    )
    translator = Translator(config)

    paths: list[Path] = []
    for argument in args.paths:
        path = Path(argument).resolve()
        if path.is_dir():
            paths.extend(iter_all_files(path, excluded))
        elif path.is_file():
            paths.append(path)
        else:
            LOGGER.warning("Path does not exist: %s", path)

    if not paths:
        print("No files to process.")
        return 0

    def process(path: Path):
        if path.suffix == ".py":
            predicate = lambda text: should_translate_non_ascii(
                text,
                config,
            )
            transform = lambda source: translate_python_tokens(
                source,
                translator,
                predicate,
                include_print_strings=True,
                include_docstrings=True,
                include_comments=True,
                batch=True,
            )
        else:
            predicate = lambda text: should_translate_non_ascii(
                text,
                config,
            )
            transform = lambda source: translate_plain_text(
                source,
                translator,
                predicate,
                batch=True,
            )

        _, changed, count = translate_file(
            path,
            translator,
            transform,
            config=config,
        )
        return path, changed, count

    print(f"Processing {len(paths)} files with {args.workers} workers...")
    stats = process_in_parallel(
        paths,
        process,
        workers=args.workers,
    )
    print(
        f"Done. Modified {stats.changed_files} files; "
        f"translated {stats.translated_items} items."
    )
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add options shared by the translation subcommands."""
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File or directory to process; default: current directory.",
    )
    parser.add_argument(
        "--target",
        default="en",
        help="Target language code; default: en.",
    )
    parser.add_argument(
        "--source",
        default="auto",
        help="Source language code; default: auto.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between individual translations; default: 0.5.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of worker threads; default: 8.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=list(DEFAULT_EXCLUDED_DIRS),
        help="Directory name to exclude; may be repeated.",
    )
    parser.add_argument(
        "--marker",
        action="append",
        default=list(DEFAULT_MARKERS),
        help="Text marker that prevents translation; may be repeated.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Write a .bak file before modifying each file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing files.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Do not translate individual strings longer than this.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    scan = subparsers.add_parser(
        "scan",
        help="pytrans.py-compatible pycld2 mode.",
    )
    add_common_arguments(scan)
    scan.set_defaults(
        handler=lambda args: run_python_mode(
            args,
            detector=should_translate_pycld2,
            include_print_strings=True,
            include_docstrings=True,
            include_comments=True,
        )
    )

    detect = subparsers.add_parser(
        "detect",
        help="pytranslator.py-compatible langdetect mode.",
    )
    add_common_arguments(detect)
    detect.set_defaults(
        handler=lambda args: run_python_mode(
            args,
            detector=should_translate_langdetect,
            include_print_strings=True,
            include_docstrings=True,
            include_comments=True,
        )
    )

    ast_mode = subparsers.add_parser(
        "ast",
        help="trans_py.py-compatible AST/docstring mode.",
    )
    add_common_arguments(ast_mode)
    ast_mode.set_defaults(
        handler=lambda args: run_python_mode(
            args,
            detector=should_translate_non_ascii,
            include_print_strings=False,
            include_docstrings=True,
            include_comments=True,
            ast_mode=True,
        )
    )

    japanese = subparsers.add_parser(
        "japanese",
        help="transjap.py-compatible Japanese-only mode.",
    )
    add_common_arguments(japanese)
    japanese.set_defaults(
        handler=lambda args: run_python_mode(
            args,
            detector=should_translate_japanese,
            include_print_strings=False,
            include_docstrings=True,
            include_comments=True,
        )
    )

    batch = subparsers.add_parser(
        "batch",
        help="ultralinetrans.py-compatible all-file batch mode.",
    )
    batch.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories; default: current directory.",
    )
    batch.add_argument("--target", default="en")
    batch.add_argument("--source", default="auto")
    batch.add_argument("--delay", type=float, default=0.5)
    batch.add_argument("--workers", type=int, default=8)
    batch.add_argument(
        "--exclude",
        action="append",
        default=list(DEFAULT_EXCLUDED_DIRS),
    )
    batch.add_argument(
        "--marker",
        action="append",
        default=list(DEFAULT_MARKERS),
    )
    batch.add_argument("--backup", action="store_true")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--max-chars", type=int, default=5000)
    batch.set_defaults(handler=run_batch_mode)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and execute the selected mode."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    raise SystemExit(main())
