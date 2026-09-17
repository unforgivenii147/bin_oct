#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate every .txt file under the given paths (or CWD) into English and write a
side-by-side JSON per file. Text is split into small chunks, language-detected with
langdetect, translated with deep-translator's GoogleTranslator, and the resulting
translation records are dumped as ``{"lines": [...]}`` next to each source file.
Uses a fixed multiprocessing.Pool of 8 workers; logging via loguru.
"""

import json
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Final

import langdetect
from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 8
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

Chunk = tuple[int, int, str]
TranslationRecord = dict[str, Any]


def chunk_file(file_path: Path, size: int = 32768) -> list[Chunk]:
    """
    Split a text file into line-range chunks whose combined length is at most
    ``size`` characters (measured in characters of the source text).

    Args:
        file_path: Path to the text file to read.
        size: Maximum character count per chunk.

    Returns:
        A list of ``(start_line, end_line, text)`` tuples. Returns an empty list
        if the file cannot be read.
    """
    chunks: list[Chunk] = []
    current_chunk: list[str] = []
    current_size: int = 0
    start_line: int = 0

    try:
        lines: list[str] = file_path.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
        for i, line in enumerate(lines):
            line_len: int = len(line)
            if current_size + line_len > size and current_chunk:
                chunks.append((start_line, i - 1, "".join(current_chunk)))
                current_chunk = [line]
                current_size = line_len
                start_line = i
            else:
                current_chunk.append(line)
                current_size += line_len
        if current_chunk:
            chunks.append((start_line, len(lines) - 1, "".join(current_chunk)))
    except Exception as exc:
        logger.error(f"Error chunking {file_path}: {exc}")

    return chunks


def detect_language(text: str) -> str | None:
    """
    Best-effort language detection on the first 500 characters of ``text``.

    Args:
        text: Source text to inspect.

    Returns:
        The ISO language code, or ``None`` if detection failed.
    """
    try:
        return langdetect.detect(text[:500])
    except Exception:
        return None


def translate_chunk(chunk_data: Chunk, index: int) -> TranslationRecord | None:
    """
    Translate a single chunk into English, unless it is already English.

    Args:
        chunk_data: ``(start_line, end_line, text)`` tuple for the chunk.
        index: Zero-based index of the chunk within its file; used to throttle
            requests (subsequent chunks sleep briefly before translating).

    Returns:
        A record describing the translation, or ``None`` if translation failed.
    """
    start_line, end_line, text = chunk_data
    if index > 0:
        time.sleep(1)

    lang: str | None = detect_language(text)
    if lang == "en":
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "translated": text,
            "skipped": True,
        }

    try:
        translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
        translated: str = translator.translate(text)
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "translated": translated,
            "skipped": False,
        }
    except Exception as exc:
        logger.error(f"Error translating chunk {start_line}-{end_line}: {exc}")
        return None


def process_file(file_path: Path) -> None:
    """
    Chunk, translate, and persist translations for a single text file.

    Args:
        file_path: Path to the source ``.txt`` file.
    """
    print(f"Processing: {file_path.name}")
    chunks: list[Chunk] = chunk_file(file_path)
    print(f"Total chunks: {len(chunks)}")

    translations: list[TranslationRecord] = []

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[TranslationRecord | None]] = [
            pool.apply_async(translate_chunk, (chunk, idx))
            for idx, chunk in enumerate(chunks)
        ]

        completed: int = 0
        for async_res in async_results:
            result: TranslationRecord | None = async_res.get()
            if result is not None:
                translations.append(result)
            completed += 1
            print(f"Progress ({file_path.name}): {completed}/{len(chunks)}")

    output_file: Path = file_path.with_suffix(".json")
    try:
        output_data: dict[str, list[TranslationRecord]] = {
            "lines": sorted(translations, key=lambda x: x["start_line"])
        }
        output_file.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✓ JSON output saved to: {output_file.name}")
    except Exception as exc:
        logger.error(f"Error saving JSON output for {file_path}: {exc}")


def get_input_files(paths: list[str]) -> list[Path]:
    """
    Resolve the list of ``.txt`` files to process.

    Args:
        paths: Explicit file or directory paths. If empty, the current working
            directory is searched recursively.

    Returns:
        A list of file paths, excluding any located under :data:`SKIP_DIRS`.
    """
    files: list[Path] = []
    search_paths: list[Path] = [Path(p) for p in paths] if paths else [Path.cwd()]

    for path in search_paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.txt"))

    return [f for f in files if not any(part in SKIP_DIRS for part in f.parts)]


def main() -> None:
    """Entry point: gather input files and translate each one."""
    input_paths: list[str] = sys.argv[1:]
    files: list[Path] = get_input_files(input_paths)

    if not files:
        print("No text files found to process.")
        return

    for file_path in files:
        try:
            process_file(file_path)
        except Exception as exc:
            logger.error(f"Unexpected error processing {file_path}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
