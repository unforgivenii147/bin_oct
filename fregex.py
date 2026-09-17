#!/data/data/com.termux/files/home/.local/bin/python
"""Extract regex patterns from Python files and save them to per-file output.

Regenerate this script: walk CWD for *.py files with pathlib, extract string literals passed to
re.compile/search/match/findall/fullmatch/finditer via a compiled regex, run the extraction with a
fixed 8-worker multiprocessing Pool chosen by --pool-method (map, starmap, imap_unordered, apply_async),
write each file's patterns to output/<flattened_relative_path>.txt, track progress with tqdm, and log with loguru.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from functools import partial
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import TypeAlias, TypedDict

from loguru import logger
from tqdm import tqdm

POOL_WORKERS: int = 8
POOL_METHODS: tuple[str, ...] = ("map", "starmap", "imap_unordered", "apply_async")

REGEX_PATTERN: re.Pattern[str] = re.compile(
    r"re\.(?:compile|search|match|findall|fullmatch|finditer)"
    r"\(\s*([rR]?)([\"'])(.*?)\2"
)

FileResult: TypeAlias = tuple[Path, int]


class PoolMethodArgs(TypedDict):
    """Arguments needed by the multiprocessing dispatch helper."""

    files: Sequence[Path]
    output_dir: Path
    method: str


def extract_regex_patterns(file_path: Path) -> list[str]:
    """Return regex pattern strings found in *file_path*, empty on read failure."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [match[2] for match in REGEX_PATTERN.findall(content)]


def process_file(file_path: Path, output_dir: Path) -> FileResult:
    """Extract patterns from *file_path* and write them under *output_dir*."""
    patterns = extract_regex_patterns(file_path)
    if patterns:
        relative_path = file_path.relative_to(Path.cwd())
        flattened = str(relative_path).replace("/", "_")
        output_file = output_dir / f"{flattened}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("\n".join(patterns), encoding="utf-8")
    return file_path, len(patterns)


def _run_pool(files: Sequence[Path], output_dir: Path, method: str) -> list[FileResult]:
    """Run *process_file* over *files* with a fixed 8-worker Pool using *method*."""
    worker = partial(process_file, output_dir=output_dir)

    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(worker, files)

        if method == "starmap":
            return pool.starmap(process_file, [(path, output_dir) for path in files])

        if method == "imap_unordered":
            return list(pool.imap_unordered(worker, files))

        if method == "apply_async":
            async_results: list[AsyncResult[FileResult]] = [
                pool.apply_async(worker, (path,)) for path in files
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def find_regex_in_dir(start_dir: Path, output_dir: Path, pool_method: str) -> None:
    """Scan *start_dir* for *.py files, extract patterns, and write results."""
    output_dir.mkdir(parents=True, exist_ok=True)

    files_to_process: list[Path] = [
        path for path in start_dir.rglob("*.py") if path.is_file()
    ]
    total_files = len(files_to_process)

    progress_bar = tqdm(total=total_files, desc="Progress", unit="file")
    try:
        results = _run_pool(files_to_process, output_dir, pool_method)
        for file_path, regex_count in results:
            if regex_count:
                logger.info(
                    f"Processed file '{file_path}' with {regex_count} regex patterns."
                )
            progress_bar.update(1)
    finally:
        progress_bar.close()

    logger.info(f"Scanning complete. Processed {total_files} files.")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for extraction.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to store extracted regex patterns.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    output_directory: Path = Path(args.output_dir)

    find_regex_in_dir(Path.cwd(), output_directory, pool_method)
    logger.info(f"Regex extraction complete. Results saved in {output_directory}")


if __name__ == "__main__":
    raise SystemExit(main())
