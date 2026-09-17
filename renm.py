#!/data/data/com.termux/files/home/.local/bin/python
"""Translate non-English filenames under a directory to English and rename each file.

Regenerate this script: walk a directory with fastwalk.walk_files, collect unique filenames whose stem
contains non-ASCII characters, translate stems via deep_translator.GoogleTranslator(auto->en) using a
fixed 8-worker multiprocessing Pool selected by --pool-method (map, starmap, imap_unordered, apply_async),
rename files deepest-first with dh.unique_path for collision safety, show tqdm progress, and log with loguru.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, TypeAlias

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from dh import unique_path  # type: ignore[import-untyped]
from fastwalk import walk_files  # type: ignore[import-untyped]
from loguru import logger
from tqdm import tqdm

DIRECTORY: Final[str] = "."
POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")

NamePair: TypeAlias = tuple[str, str]


def is_english(text: str) -> bool:
    """Return True when *text* contains only ASCII characters."""
    return NON_ENGLISH_PATTERN.search(text) is None


def translate_name(name: str) -> NamePair:
    """Return ``(original_name, translated_name)`` translating the stem if non-English."""
    path = Path(name)
    stem = path.stem
    suffix = path.suffix

    if is_english(stem):
        return (name, name)

    try:
        translated = GoogleTranslator(source="auto", target="en").translate(stem)
        if not translated:
            return (name, name)
        return (name, translated + suffix)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Translation failed for '{stem}': {exc}")
        return (name, name)


def _translate_name_tuple(item: tuple[str]) -> NamePair:
    """Tuple-argument wrapper around :func:`translate_name` for ``Pool.map``."""
    return translate_name(item[0])


def _run_pool(names: Sequence[str], method: str) -> list[NamePair]:
    """Translate *names* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_translate_name_tuple, [(name,) for name in names])

        if method == "starmap":
            return pool.starmap(translate_name, [(name,) for name in names])

        if method == "imap_unordered":
            return list(
                pool.imap_unordered(_translate_name_tuple, [(n,) for n in names])
            )

        if method == "apply_async":
            async_results: list[AsyncResult[NamePair]] = [
                pool.apply_async(translate_name, (name,)) for name in names
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def _build_translation_map(paths: Sequence[Path], pool_method: str) -> dict[str, str]:
    """Translate the unique non-English filenames in *paths* and return a name map."""
    unique_names: list[str] = sorted(
        {path.name for path in paths if not is_english(path.name)}
    )
    if not unique_names:
        return {}

    translation_map: dict[str, str] = {}
    for original, translated in tqdm(
        _run_pool(unique_names, pool_method),
        total=len(unique_names),
        desc="Translating filenames",
    ):
        translation_map[original] = translated
    return translation_map


def rename_files(directory: Path, pool_method: str) -> None:
    """Translate and rename non-English filenames under *directory*."""
    if not directory.exists() or not directory.is_dir():
        logger.error(f"Not a directory: {directory}")
        return

    paths: list[Path] = [Path(p) for p in walk_files(str(directory))]
    if not paths:
        logger.info("No files found.")
        return

    translation_map = _build_translation_map(paths, pool_method)
    if not translation_map:
        logger.info("No non-English filenames found.")
        return

    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        new_name = translation_map.get(path.name)
        if new_name is None or new_name == path.name:
            continue

        new_path = unique_path(path.with_name(new_name))
        try:
            path.rename(new_path)
            logger.info(f"Renamed: {path.name} -> {new_path.name}")
        except OSError as exc:
            logger.error(f"Error renaming {path.name}: {exc}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        default=DIRECTORY,
        help="Directory to scan and rename.",
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

    rename_files(directory, pool_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
