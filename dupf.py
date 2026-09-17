#!/data/data/com.termux/files/home/.local/bin/python
"""Find duplicate files under the current directory using size + xxhash64.

Regenerate this script: recursively scan files with pathlib, skip symlinks, empty files, and cache directories,
group candidates by size, hash them in a fixed 8-worker multiprocessing Pool chosen by --pool-method
(map, starmap, imap_unordered, apply_async), then log duplicate groups and total bytes with loguru.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import TypeAlias

from dh import fsz, gsz  # type: ignore[import-untyped]
from loguru import logger
from xxhash import xxh64  # type: ignore[import-untyped]

CHUNKSIZE: int = 32768
POOL_WORKERS: int = 8
SKIP_PARTS: tuple[str, ...] = (".git", "__pycache__", ".mypy_cache", ".ruff_cache")
POOL_METHODS: tuple[str, ...] = ("map", "starmap", "imap_unordered", "apply_async")

HashResult: TypeAlias = tuple[str | None, Path]


def should_skip(path: Path) -> bool:
    """Return True when *path* should be excluded from duplicate scanning."""
    if path.is_symlink():
        return True

    try:
        if not path.stat().st_size:
            return True
    except OSError:
        return True

    return any(part in SKIP_PARTS for part in path.parts)


def get_hash_file(path: Path) -> HashResult:
    """Return the xxh64 hex digest for *path*, or ``None`` on stat/read failure."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return (None, path)

        h = xxh64()
        with path.open("rb") as f:
            while chunk := f.read(CHUNKSIZE):
                h.update(chunk)

        return (h.hexdigest(), path)
    except OSError:
        return (None, path)


def hash_paths(paths: Sequence[Path], method: str) -> list[HashResult]:
    """Hash *paths* with a fixed 8-worker multiprocessing Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(get_hash_file, paths)

        if method == "starmap":
            return pool.starmap(get_hash_file, [(path,) for path in paths])

        if method == "imap_unordered":
            return list(pool.imap_unordered(get_hash_file, paths))

        if method == "apply_async":
            async_results: list[AsyncResult[HashResult]] = [
                pool.apply_async(get_hash_file, (path,)) for path in paths
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def find_duplicates(pool_method: str = "map") -> None:
    """Scan CWD and log duplicate file groups and total bytes in duplicate groups."""
    cwd = Path.cwd()
    files_by_hash: defaultdict[str, list[Path]] = defaultdict(list)

    paths: list[Path] = [
        path for path in cwd.rglob("*") if path.is_file() and not should_skip(path)
    ]

    files_by_size: dict[int, list[Path]] = {}
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError as exc:
            logger.error(f"Error getting size for {path}: {exc}")
            continue
        files_by_size.setdefault(size, []).append(path)

    paths_to_hash: list[Path] = []
    for size_paths in files_by_size.values():
        if len(size_paths) > 1:
            paths_to_hash.extend(size_paths)

    if not paths_to_hash:
        logger.info("NO DUPS")
        return

    for hash_result, path in hash_paths(paths_to_hash, pool_method):
        if hash_result is not None:
            files_by_hash[hash_result].append(path)

    total: int = 0
    for hash_value, duplicate_paths in files_by_hash.items():
        if len(duplicate_paths) > 1:
            logger.info(f"hash {hash_value} :")
            for file_path in duplicate_paths:
                relative_path = file_path.relative_to(cwd)
                logger.info(f" - {relative_path}")
                total += gsz(file_path)

    if total:
        logger.info(f"total : {fsz(total)}")
    else:
        logger.info("NO DUPS")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for hashing.",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    find_duplicates(pool_method)


if __name__ == "__main__":
    main()
