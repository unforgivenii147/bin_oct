#!/data/data/com.termux/files/home/.local/bin/python
"""Translate Persian (Farsi) lines in a text file to English and save aligned output.

Regenerate this script: read a UTF-8 text file with pathlib, filter lines containing Arabic-script
characters, translate each via deep_translator.GoogleTranslator(fa->en) using a fixed 8-worker
multiprocessing Pool selected by --pool-method (map, starmap, imap_unordered, apply_async), write
"<source> = <translation>" lines to <stem>_en<suffix>, and log with loguru.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import partial
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, TypeAlias

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from loguru import logger

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

PERSIAN_RANGE: Final[tuple[str, str]] = ("\u0600", "\u06ff")

Translation: TypeAlias = tuple[str, str]


def translate_line(line: str) -> Translation | None:
    """Translate a single Persian *line* to English, or None if skipped/failed."""
    stripped = line.strip()
    if not stripped:
        return None

    if not any(PERSIAN_RANGE[0] <= char <= PERSIAN_RANGE[1] for char in stripped):
        return None

    try:
        translator = GoogleTranslator(source="fa", target="en")
        result = translator.translate(stripped)
        if not result:
            return None
        logger.info(f"{stripped} == {result}")
        return (stripped, result)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Translation error for '{stripped[:20]}': {exc}")
        return None


def _run_pool(lines: Sequence[str], method: str) -> list[Translation]:
    """Translate *lines* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            raw = pool.map(translate_line, lines)
        elif method == "starmap":
            raw = pool.starmap(translate_line, [(line,) for line in lines])
        elif method == "imap_unordered":
            raw = list(pool.imap_unordered(translate_line, lines))
        elif method == "apply_async":
            async_results: list[AsyncResult[Translation | None]] = [
                pool.apply_async(translate_line, (line,)) for line in lines
            ]
            raw = [result.get() for result in async_results]
        else:
            raise ValueError(f"Unsupported pool method: {method}")

    return [item for item in raw if item is not None]


def translate_file(file_input: Path, pool_method: str) -> None:
    """Translate Persian lines in *file_input* and write the aligned output file."""
    if not file_input.exists():
        logger.error(f"File not found: {file_input}")
        return

    try:
        lines = file_input.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error reading file: {exc}")
        return

    out_path = file_input.parent / f"{file_input.stem}_en{file_input.suffix}"
    logger.info(f"Translating {len(lines)} lines from {file_input.name}...")

    results: list[Translation] = _run_pool(lines, pool_method)

    for text, translated in results:
        logger.info(f"{text} -> {translated}")

    try:
        with out_path.open("w", encoding="utf-8") as f:
            for text, translated in results:
                f.write(f"{text} = {translated}\n")
        logger.info(f"✓ Translated output saved to {out_path}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error writing output file: {exc}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_path", help="Path to the Persian text file to translate.")
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
    file_input: Path = Path(args.file_path)

    translate_file(file_input, pool_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
