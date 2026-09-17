#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate Persian text found in .txt/.md/.py/.json/.csv files to English in place.
Each file is split into ~4900-character chunks on word/sentence boundaries, and
each chunk containing Persian characters is translated via deep-translator's
GoogleTranslator using a fixed multiprocessing.Pool of 8 workers. Directories
listed in SKIP_DIRS and any dotfile paths are ignored. Logging via loguru.
"""

import re
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 8
CHUNK_DELAY: Final[float] = 1.5
FILE_DELAY: Final[float] = 2.0
TARGET_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".txt", ".md", ".py", ".json", ".csv"}
)
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
PERSIAN_PATTERN: Final[re.Pattern[str]] = re.compile(
    "[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]"
)
BOUNDARY_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s\n\.\!\?\;]+")


def split_into_chunks(text: str, size: int = 4900) -> list[str]:
    """
    Split ``text`` into chunks of at most ``size`` characters, preferring to
    break on whitespace/punctuation boundaries.

    Args:
        text: The source text to split.
        size: Maximum number of characters per chunk.

    Returns:
        A list of chunks whose concatenation equals the original text.
    """
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    pos: int = 0

    while pos < len(text):
        end: int = min(pos + size, len(text))

        if end == len(text):
            chunks.append(text[pos:])
            break

        boundary_match: re.Match[str] | None = None
        for match in BOUNDARY_PATTERN.finditer(text, pos, end):
            boundary_match = match

        if boundary_match is not None and boundary_match.end() > pos:
            split_pos: int = boundary_match.end()
        else:
            split_pos = end

        chunks.append(text[pos:split_pos])
        pos = split_pos

    return chunks


def translate_chunk(chunk: str) -> str:
    """
    Translate a single chunk of text from Persian to English.

    Chunks with no Persian characters are returned unchanged. Successful
    translations pause for :data:`CHUNK_DELAY` seconds to throttle the
    upstream translation service.

    Args:
        chunk: The text fragment to translate.

    Returns:
        The translated text, or the original chunk if translation failed or
        was unnecessary.
    """
    if not PERSIAN_PATTERN.search(chunk):
        return chunk

    try:
        translator: GoogleTranslator = GoogleTranslator(source="fa", target="en")
        result: str | None = translator.translate(chunk)
        if result:
            print(f"Chunk translated: {result[:30].replace(chr(10), ' ')}...")
            time.sleep(CHUNK_DELAY)
            return result
        return chunk
    except Exception as exc:
        logger.error(f"Chunk translation error: {exc}")
        return chunk


def translate_file(path: Path) -> None:
    """
    Translate Persian content in a single file in place.

    Reads the file as UTF-8, skips it if no Persian text is present, splits the
    content into chunks, translates each chunk in parallel via a fixed
    :class:`multiprocessing.Pool`, and rewrites the file with the joined result.

    Args:
        path: The file to translate.
    """
    try:
        content: str = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Skipping unreadable file {path}: {exc}")
        return

    if not PERSIAN_PATTERN.search(content):
        return

    print(f"Translating: {path.name}")
    chunks: list[str] = split_into_chunks(content)

    translated_chunks: list[str] = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[str]] = [
            pool.apply_async(translate_chunk, (chunk,)) for chunk in chunks
        ]
        for async_res in async_results:
            translated_chunks.append(async_res.get())

    translated_text: str = "".join(translated_chunks)

    try:
        path.write_text(translated_text, encoding="utf-8")
        print(f"✓ Updated: {path.name}")
    except Exception as exc:
        logger.error(f"Error writing to {path}: {exc}")

    time.sleep(FILE_DELAY)


def get_files(path: Path) -> list[Path]:
    """
    Recursively find target files under ``path``.

    Skips dotfile paths and directories listed in :data:`SKIP_DIRS`; only
    includes files whose suffix is in :data:`TARGET_SUFFIXES`.

    Args:
        path: Directory to search.

    Returns:
        A sorted list of matching file paths.
    """
    files: list[Path] = []
    for p in path.rglob("*"):
        if any(part.startswith(".") or part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in TARGET_SUFFIXES:
            files.append(p)
    return sorted(files)


def main() -> None:
    """Entry point: locate target files and translate each one."""
    directory: str = sys.argv[1] if len(sys.argv) > 1 else "."
    start_path: Path = Path(directory)

    if not start_path.exists():
        logger.error(f"Path does not exist: {directory}")
        sys.exit(1)

    files: list[Path] = get_files(start_path)
    if not files:
        print("No files found to process.")
        return

    print(f"Processing {len(files)} files...")
    for f in files:
        translate_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
