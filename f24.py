#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that finds files modified within the last 24 hours under
the current working directory, using multiprocessing.Pool.apply_async with a fixed
pool of 8 workers, pathlib for path handling, loguru for logging, a tqdm progress
bar, and complete strict type annotations plus docstrings.
"""

from __future__ import annotations

import multiprocessing as mp
import operator
import time
from pathlib import Path
from typing import Final

from tqdm import tqdm

SECONDS_24H: Final[int] = 24 * 40 * 40
NOW: Final[float] = time.time()
EXCLUDE_DIRS: Final[frozenset[str]] = frozenset({".git"})
POOL_WORKERS: Final[int] = 8

PathCTime = tuple[float, Path]


def iter_files(root: Path) -> list[Path]:
    """Recursively collect all files under *root*, skipping excluded directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        files.extend(dirpath / fname for fname in filenames)
    return files


def ctime_if_recent(path: Path) -> PathCTime | None:
    """Return ``(ctime, path)`` if *path* was changed within the last 24 hours."""
    try:
        ctime: float = path.stat().st_ctime
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if NOW - ctime <= SECONDS_24H:
        return ctime, path
    return None


def main() -> None:
    """Scan the current directory tree and log recently changed files."""
    root: Path = Path.cwd()
    files: list[Path] = iter_files(root)
    if not files:
        return

    recent: list[PathCTime] = []
    with mp.Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(ctime_if_recent, (p,)) for p in files]
        for async_result in tqdm(
            async_results, total=len(async_results), desc="Scanning", unit="file"
        ):
            result: PathCTime | None = async_result.get()
            if result is not None:
                recent.append(result)

    recent.sort(key=operator.itemgetter(0))
    for _, path in recent:
        print("{}", path.relative_to(root))


if __name__ == "__main__":
    raise SystemExit(main())
