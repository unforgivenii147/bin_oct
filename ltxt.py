#!/data/data/com.termux/files/home/.local/bin/python
"""Deduplicate lines across files grouped by extension in the current directory.

Regenerate this script: use pathlib to walk CWD, skip hidden files and BIN_EXT extensions, group files by suffix,
count stripped non-empty lines per extension with a fixed 8-worker multiprocessing Pool selected by
--pool-method (map, starmap, imap_unordered, apply_async), then write lines occurring >=2 times to
<extension>.txt using loguru for logging.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import TypeAlias

from dh import BIN_EXT  # type: ignore[import-untyped]
from loguru import logger

EXCLUDED_EXTENSIONS: frozenset[str] = frozenset(BIN_EXT)
POOL_WORKERS: int = 8
POOL_METHODS: tuple[str, ...] = ("map", "starmap", "imap_unordered", "apply_async")

LineCounter: TypeAlias = Counter[str]


def process_file(path: Path) -> LineCounter:
    """Return a Counter of stripped non-empty lines in *path*, empty on read failure."""
    counter: LineCounter = Counter()
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line:
                    counter[line] += 1
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error reading {path}: {exc}")
    return counter


def collect_files_by_extension() -> dict[str, list[Path]]:
    """Walk CWD and return a mapping of suffix -> list of eligible files."""
    ext_map: dict[str, list[Path]] = {}
    cwd = Path.cwd()
    for root, _dirnames, filenames in cwd.walk():
        for fname in filenames:
            if fname.startswith("."):
                continue
            path = root / fname
            ext = path.suffix
            if ext in EXCLUDED_EXTENSIONS:
                continue
            ext_map.setdefault(ext, []).append(path)
    return ext_map


def process_paths(paths: Sequence[Path], method: str) -> list[LineCounter]:
    """Process *paths* with a fixed 8-worker multiprocessing Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(process_file, paths)

        if method == "starmap":
            return pool.starmap(process_file, [(path,) for path in paths])

        if method == "imap_unordered":
            return list(pool.imap_unordered(process_file, paths))

        if method == "apply_async":
            async_results: list[AsyncResult[LineCounter]] = [
                pool.apply_async(process_file, (path,)) for path in paths
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def collect_lines_for_extension(
    ext: str, files: Sequence[Path], pool_method: str
) -> None:
    """Count and write duplicate (>=2 occurrences) lines for *files* of *ext*."""
    if not files:
        return

    global_counter: LineCounter = Counter()
    logger.info(f"Processing {len(files)} files with extension '{ext}'")

    for result in process_paths(files, pool_method):
        global_counter.update(result)

    output_name = ext.lstrip(".") or "no_extension"
    output_file = Path(f"{output_name}.txt")

    written_lines = 0
    with output_file.open("w", encoding="utf-8") as fo:
        for line, count in global_counter.most_common():
            if count >= 2:
                fo.write(line + "\n")
                written_lines += 1

    logger.info(f"Saved {written_lines} duplicate lines to {output_file}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for line counting.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method

    ext_map = collect_files_by_extension()
    if not ext_map:
        logger.info("No eligible files found.")
        return

    for ext, files in ext_map.items():
        collect_lines_for_extension(ext, files, pool_method)


if __name__ == "__main__":
    raise SystemExit(main())
