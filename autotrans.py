#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate all non-binary text files under a target directory into English,
writing each result to a sibling file named ``<stem>_eng<suffix>``. Files are
dispatched to a fixed multiprocessing.Pool of 8 workers; each file's content is
split into 32 KiB chunks and translated sequentially within its worker (nested
multiprocessing pools are intentionally avoided). Uses deep-translator's
GoogleTranslator; logging via loguru.
"""

import re
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from dh import is_binary  # type: ignore[import-untyped]
from loguru import logger

DIRECTORY: Final[str] = "."
CHUNK_SIZE: Final[int] = 32768
MAX_WORKERS: Final[int] = 8
NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")

# Optional fast directory walker; falls back to Path.rglob if unavailable.
_walk_files: object
try:
    from fastwalk import walk_files as _walk_files  # type: ignore[import-untyped]

    _HAS_FASTWALK: bool = True
except ImportError:
    _walk_files = None
    _HAS_FASTWALK = False


def split_into_chunks(text: str, size: int) -> list[str]:
    """
    Split ``text`` into fixed-size character slices.

    Args:
        text: The source text to slice.
        size: Maximum number of characters per slice.

    Returns:
        A list of chunks whose concatenation equals ``text``.
    """
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    """
    Translate a single chunk of text to English.

    Args:
        chunk: The text fragment to translate.

    Returns:
        The translated text, or the original chunk if it is empty or the
        translation call fails / returns nothing.
    """
    if not chunk.strip():
        return chunk
    try:
        translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
        result: str | None = translator.translate(chunk)
        return result if result else chunk
    except Exception as exc:
        logger.error(f"Chunk translation failed: {exc}")
        return chunk


def contains_non_english(text: str) -> bool:
    """
    Return whether ``text`` contains any non-ASCII character.

    Args:
        text: The text to inspect.

    Returns:
        ``True`` if any non-ASCII byte/charcode is present.
    """
    return bool(NON_ENGLISH_PATTERN.search(text))


def translate_file(path: Path) -> None:
    """
    Translate a single file's content and write the output alongside it.

    Chunks of the source file are translated serially within this function
    because it may itself be running inside a worker process of the outer
    :class:`multiprocessing.Pool` (nested pools can deadlock).

    Args:
        path: The source file to translate.
    """
    print(f"Processing file: {path}")
    try:
        content: str = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.error(f"Cannot read file {path}: {exc}")
        return

    if not contains_non_english(content):
        print(f"File is already English: {path.name}")
        return

    print(f"Non-English content detected in: {path.name}")
    chunks: list[str] = split_into_chunks(content, CHUNK_SIZE)
    print(f"Total chunks: {len(chunks)}. Translating...")

    translated_chunks: list[str] = [translate_chunk(chunk) for chunk in chunks]
    translated_text: str = "".join(translated_chunks)

    new_path: Path = path.with_stem(f"{path.stem}_eng")
    try:
        new_path.write_text(translated_text, encoding="utf-8")
        print(f"✓ Translated → {new_path.name}")
    except Exception as exc:
        logger.error(f"Failed to write output file {new_path}: {exc}")


def scan_files(directory: Path) -> list[Path]:
    """
    Collect every non-binary file under ``directory``.

    Uses ``fastwalk.walk_files`` when available, otherwise falls back to
    :meth:`pathlib.Path.rglob` and skips hidden components.

    Args:
        directory: Root directory to scan.

    Returns:
        A list of candidate file paths.
    """
    files: list[Path] = []

    if _HAS_FASTWALK and _walk_files is not None:
        walker = _walk_files  # type: ignore[assignment]
        for pth in walker(str(directory)):  # type: ignore[misc]
            p: Path = Path(pth)
            if p.is_file() and not is_binary(p):
                files.append(p)
    else:
        for p in directory.rglob("*"):
            if (
                p.is_file()
                and not any(part.startswith(".") for part in p.parts)
                and not is_binary(p)
            ):
                files.append(p)

    return files


def process_directory(directory: str) -> None:
    """
    Scan ``directory`` and translate every candidate file in parallel.

    Args:
        directory: Directory path to scan.
    """
    print(f"Scanning directory: {directory}")
    dir_path: Path = Path(directory)

    files: list[Path] = scan_files(dir_path)
    print(f"Total text files found: {len(files)}")

    if not files:
        return

    print("Starting parallel file translation...\n")

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[None]] = [
            pool.apply_async(translate_file, (f,)) for f in files
        ]
        for f, async_res in zip(files, async_results):
            try:
                async_res.get()
            except Exception as exc:
                logger.error(f"Unexpected error processing {f}: {exc}")


def main() -> None:
    """Entry point: translate every text file under :data:`DIRECTORY`."""
    process_directory(DIRECTORY)


if __name__ == "__main__":
    raise SystemExit(main())
