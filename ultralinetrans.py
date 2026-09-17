#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python script that translates non-English comments and string literals in source files to English.

The script walks the current working directory (or accepts explicit file paths as arguments),
skips binary files and common cache/virtualenv directories, and processes each remaining file.
Python files are tokenized so that only COMMENT tokens and STRING tokens containing non-ASCII
text are translated via GoogleTranslator, preserving code structure. Non-Python text files are
translated wholesale. Work is dispatched to a multiprocessing.Pool with 8 workers using
apply_async, results are collected, and files are atomically overwritten via a temporary file
in the same directory. Uses loguru for logging and pathlib for all path handling.
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import tokenize
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from dh import DOC_TH1, DOC_TH2, get_files, is_binary
from loguru import logger

CHUNK_SIZE: Final[int] = 4990
POOL_WORKERS: Final[int] = 8

SKIP_DIRS: Final[frozenset[str]] = frozenset(
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

NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")

TokenTuple = tuple[int, str, tuple[int, int], tuple[int, int], str]
TranslationTarget = tuple[int, str] | tuple[int, str, str]


def is_english(text: str) -> bool:
    """Return True if the given text contains only ASCII characters."""
    return not NON_ENGLISH_PATTERN.search(text)


def batch_translate(texts: list[str]) -> list[str]:
    """Translate a list of strings to English using GoogleTranslator.

    Attempts to translate all strings in a single batched request using a
    unique separator. Falls back to individual translations if the batch
    response cannot be split back into the same number of items.
    """
    if not texts:
        return []

    separator = "\n===|||===\n"
    combined_text = separator.join(texts)

    try:
        translated_combined: str | None = GoogleTranslator(
            source="auto", target="en"
        ).translate(combined_text)
        if not translated_combined:
            return texts

        translated_list = [
            t.strip() for t in translated_combined.split(separator.strip())
        ]

        if len(translated_list) != len(texts):
            logger.warning(
                f"Batch mismatch ({len(translated_list)} vs {len(texts)}). "
                "Falling back to individual translation."
            )
            return [
                GoogleTranslator(source="auto", target="en").translate(t) or t
                for t in texts
            ]

        return translated_list
    except Exception as e:
        logger.error(f"Batch translation error: {e}")
        return texts


def safe_overwrite(path: Path, content: str) -> None:
    """Atomically overwrite path with content via a temp file in the same dir."""
    tmp_path: Path
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(str(tmp_path), str(path))


def translate_python_file(source: str) -> str:
    """Translate non-English comments and string literals within Python source."""
    try:
        tokens: list[TokenTuple] = list(
            tokenize.generate_tokens(io.StringIO(source).readline)
        )
    except (tokenize.TokenError, IndentationError):
        return batch_translate([source])[0]

    to_translate: list[str] = []
    translation_targets: list[TranslationTarget] = []

    for idx, token in enumerate(tokens):
        tok_type: int = token[0]
        tok_str: str = token[1]

        if tok_type == tokenize.COMMENT and not is_english(tok_str):
            comment_text = tok_str[1:].strip()
            if comment_text:
                to_translate.append(comment_text)
                translation_targets.append((idx, "COMMENT"))
        elif tok_type == tokenize.STRING:
            stripped = tok_str.strip("'\"")
            if stripped and not is_english(stripped) and len(stripped) > 5:
                to_translate.append(stripped)
                translation_targets.append((idx, "STRING", tok_str))

    if not to_translate:
        return source

    translated_texts = batch_translate(to_translate)

    for target_info, translated_str in zip(
        translation_targets, translated_texts, strict=False
    ):
        idx = target_info[0]
        tok_type = target_info[1]
        if tok_type == "COMMENT":
            tokens[idx] = (
                tokenize.COMMENT,
                f"# {translated_str}",
                tokens[idx][2],
                tokens[idx][3],
                tokens[idx][4],
            )
        elif tok_type == "STRING":
            orig_tok_str = target_info[2]  # type: ignore[index]
            quote_char = (
                orig_tok_str[:3]
                if orig_tok_str.startswith((DOC_TH1, DOC_TH2))
                else orig_tok_str[0]
            )
            tokens[idx] = (
                tokenize.STRING,
                f"{quote_char}{translated_str}{quote_char}",
                tokens[idx][2],
                tokens[idx][3],
                tokens[idx][4],
            )

    try:
        return tokenize.untokenize(tokens).decode("utf-8")  # type: ignore[union-attr]
    except Exception as e:
        logger.error(f"Error rebuilding python file structure: {e}")
        return source


def process_file(path: Path) -> None:
    """Translate non-English content in the given file, overwriting it in place."""
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return

    if is_english(original.strip()):
        return

    print(f"Processing {path.name}...")

    try:
        translated: str
        if path.suffix == ".py":
            translated = translate_python_file(original)
        else:
            translated = batch_translate([original])[0]

        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            print(f"✓ Updated {path.name}")
    except Exception as e:
        logger.error(f"Failed to process {path}: {e}")


def main() -> None:
    """Entry point: gather files and dispatch translation tasks to a Pool."""
    args: list[str] = sys.argv[1:]
    files: list[Path] = (
        [Path(p) for p in args]
        if args
        else [f for f in get_files(Path.cwd()) if not is_binary(f)]
    )

    if not files:
        print("No files to process.")
        return

    with Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in files]
        for result in async_results:
            try:
                result.get()
            except Exception as e:
                logger.error(f"Task failed: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
