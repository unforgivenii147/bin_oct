#!/data/data/com.termux/files/home/.local/bin/python
"""Swap ``import re`` with ``import regex as re`` (or reverse) across all Python files in CWD.

Regenerate this script: parse --reverse (and optional --pool-method), recursively find *.py files under
CWD with pathlib, replace the first matching import line in each file using a regex pattern, run the
update with a fixed 8-worker multiprocessing Pool selected by --pool-method (map, starmap,
imap_unordered, apply_async), and log modified/errored files with loguru.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, TypeAlias

from loguru import logger

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

NORMAL_IMPORT: Final[str] = r"^import re\b"
REGEX_IMPORT: Final[str] = r"^import regex as re\b"

FileResult: TypeAlias = str | None
UpdateTask: TypeAlias = tuple[Path, bool]


def get_pyfiles(root: Path) -> list[Path]:
    """Return all ``*.py`` files under *root*."""
    return [p for p in root.rglob("*.py") if p.is_file()]


def update_file(file_path: Path, reverse: bool = False) -> FileResult:
    """Swap the first matching import line in *file_path*; return a status message or ``None``."""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return f"Error processing {file_path}: {exc}"

    new_lines: list[str] = []
    changed = False
    search_pat = REGEX_IMPORT if reverse else NORMAL_IMPORT
    replacement = "import re" if reverse else "import regex as re"

    for line in lines:
        if not changed and re.match(search_pat, line):
            new_lines.append(re.sub(search_pat, replacement, line))
            changed = True
        else:
            new_lines.append(line)

    if not changed:
        return None

    try:
        file_path.write_text("".join(new_lines), encoding="utf-8")
    except OSError as exc:
        return f"Error processing {file_path}: {exc}"

    return f"Updated: {file_path}"


def _update_file_tuple(task: UpdateTask) -> FileResult:
    """Tuple-argument wrapper around :func:`update_file` for ``Pool.map``."""
    path, reverse = task
    return update_file(path, reverse)


def _run_pool(tasks: Sequence[UpdateTask], method: str) -> list[FileResult]:
    """Update *tasks* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_update_file_tuple, tasks)

        if method == "starmap":
            return pool.starmap(update_file, tasks)

        if method == "imap_unordered":
            return list(pool.imap_unordered(_update_file_tuple, tasks))

        if method == "apply_async":
            async_results: list[AsyncResult[FileResult]] = [
                pool.apply_async(_update_file_tuple, (task,)) for task in tasks
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Recursively swap 'import re' with 'import regex as re'"
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Reverse the replacement (regex as re -> re)",
    )
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for updates.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    reverse: bool = bool(args.reverse)
    pool_method: str = args.pool_method

    cwd = Path.cwd()
    py_files = get_pyfiles(cwd)
    logger.info(f"Scanning {len(py_files)} files...")

    tasks: list[UpdateTask] = [(path, reverse) for path in py_files]
    if not tasks:
        logger.info("Task complete. Files modified: 0")
        return 0

    results = _run_pool(tasks, pool_method)
    updates: list[str] = [r for r in results if r is not None]
    for msg in updates:
        logger.info(msg)

    logger.info(f"Task complete. Files modified: {len(updates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
