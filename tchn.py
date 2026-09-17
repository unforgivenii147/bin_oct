#!/data/data/com.termux/files/home/.local/bin/python
"""Translate non-ASCII text files in a directory to English and save as <stem>_eng<suffix>.

Regenerate this script: walk a directory with pathlib, keep binary-free files containing non-ASCII bytes,
split each into CHUNK_SIZE chunks, translate chunks via deep_translator.GoogleTranslator(auto->en) using
a fixed 8-worker multiprocessing Pool selected by --pool-method (map, starmap, imap_unordered, apply_async),
reassemble per-file output and write <stem>_eng<suffix>, logging everything with loguru.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, TypeAlias

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

DIRECTORY: Final[str] = "."
CHUNK_SIZE: Final[int] = 32768
POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")

ChunkTask: TypeAlias = tuple[Path, int, str]
ChunkResult: TypeAlias = tuple[Path, int, str]


def is_text_file(path: Path) -> bool:
    """Return True when *path* appears to be a text file (no NUL byte in the first 2 KiB)."""
    try:
        with path.open("rb") as f:
            chunk = f.read(2048)
        return b"\x00" not in chunk
    except OSError:
        return False


def split_into_chunks(text: str, size: int) -> list[str]:
    """Split *text* into a list of substrings of length *size*."""
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    """Translate *chunk* from auto-detected language to English, returning it on failure."""
    try:
        return GoogleTranslator(source="auto", target="en").translate(chunk)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Chunk translation error: {exc}")
        return chunk


def _translate_task(path: Path, index: int, chunk: str) -> ChunkResult:
    """Translate one chunk and return it with its source path and index."""
    return (path, index, translate_chunk(chunk))


def _translate_task_tuple(task: ChunkTask) -> ChunkResult:
    """Tuple-argument wrapper around :func:`_translate_task` for ``Pool.map``."""
    return _translate_task(*task)


def _run_pool(tasks: Sequence[ChunkTask], method: str) -> list[ChunkResult]:
    """Run chunk translation tasks with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_translate_task_tuple, tasks)

        if method == "starmap":
            return pool.starmap(_translate_task, tasks)

        if method == "imap_unordered":
            return list(pool.imap_unordered(_translate_task_tuple, tasks))

        if method == "apply_async":
            async_results: list[AsyncResult[ChunkResult]] = [
                pool.apply_async(_translate_task_tuple, (task,)) for task in tasks
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def _collect_tasks(files: Sequence[Path]) -> list[ChunkTask]:
    """Build a flat list of (path, chunk_index, chunk_text) tasks from *files*."""
    tasks: list[ChunkTask] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Skipping unreadable file {path}: {exc}")
            continue

        if not NON_ENGLISH_PATTERN.search(content):
            continue

        for index, chunk in enumerate(split_into_chunks(content, CHUNK_SIZE)):
            tasks.append((path, index, chunk))

    return tasks


def _write_translated_files(results: Sequence[ChunkResult]) -> None:
    """Group chunk results by source file and write the translated output files."""
    by_file: dict[Path, list[tuple[int, str]]] = {}
    for path, index, translated in results:
        by_file.setdefault(path, []).append((index, translated))

    for path, chunks in by_file.items():
        chunks.sort(key=lambda item: item[0])
        translated_text = "".join(text for _, text in chunks)
        new_path = path.parent / f"{path.stem}_eng{path.suffix}"
        try:
            new_path.write_text(translated_text, encoding="utf-8")
            logger.info(f"Translated → {new_path.name}")
        except OSError as exc:
            logger.error(f"Error writing {new_path}: {exc}")


def process_directory(directory: Path, pool_method: str) -> None:
    """Walk *directory*, translate eligible text files, and save *_eng* outputs."""
    if not directory.exists() or not directory.is_dir():
        logger.error(f"Not a directory: {directory}")
        return

    files: list[Path] = [
        path for path in directory.rglob("*") if path.is_file() and is_text_file(path)
    ]
    logger.info(f"Found {len(files)} text files to process")

    if not files:
        return

    tasks = _collect_tasks(files)
    if not tasks:
        logger.info("No non-English content found; nothing to translate.")
        return

    results = _run_pool(tasks, pool_method)
    _write_translated_files(results)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        default=DIRECTORY,
        help="Directory to scan for text files.",
    )
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for translation.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    directory: Path = Path(args.directory)

    process_directory(directory, pool_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
