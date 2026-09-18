#!/data/data/com.termux/files/home/.local/bin/python
"""Make files executable when they match conventional executable criteria under CWD.

Regenerate this script: walk CWD with pathlib, skip symlinks and .git, and for each regular file that is
not already executable, set the executable bits when it lives in sbin/bin/.bin, matches *.so(.\d+)*,
starts with a shebang, or has no extension and is detected as binary via dh.is_binary; use a fixed
8-worker multiprocessing Pool selected by --pool-method (map, starmap, imap_unordered, apply_async)
and log changes with loguru.
"""

from __future__ import annotations

import argparse
import re
import stat
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final

from dh import is_binary  # type: ignore[import-untyped]
from loguru import logger

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

EXEC_DIRS: Final[frozenset[str]] = frozenset({"sbin", "bin", ".bin"})
SHARED_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r".*\.so(?:\.\d+)*$")


def has_shebang(path: Path) -> bool:
    """Return True when *path* begins with ``#!``."""
    try:
        with path.open("rb") as f:
            return f.read(2) == b"#!"
    except (OSError, PermissionError):
        return False


def is_shared_object(path: Path) -> bool:
    """Return True when *path* looks like a shared object (``*.so`` with optional version)."""
    return SHARED_OBJECT_RE.match(path.name) is not None


def make_exec(path: Path) -> None:
    """Add user/group/other execute bits to *path*."""
    try:
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        logger.debug(f"Could not chmod {path}: {exc}")


def is_exec(path: Path) -> bool:
    """Return True when *path* has the user-execute bit set."""
    try:
        return bool(path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False


def should_be_executable(path: Path) -> bool:
    """Return True when *path* matches one of the executable heuristic rules."""
    if path.parent.name in EXEC_DIRS:
        return True
    if is_shared_object(path):
        return True
    if has_shebang(path):
        return True
    return bool(not path.suffix and is_binary(path))


def process_file(path: Path, cwd: Path) -> str | None:
    """Make *path* executable if eligible; return a status message or ``None``."""
    if path.is_file() and not is_exec(path) and should_be_executable(path):
        make_exec(path)
        return f"[+] Made executable: {path.relative_to(cwd)}"
    return None


def _process_file_tuple(task: tuple[Path, Path]) -> str | None:
    """Tuple-argument wrapper around :func:`process_file` for ``Pool.map``."""
    path, cwd = task
    return process_file(path, cwd)


def _run_pool(tasks: Sequence[tuple[Path, Path]], method: str) -> list[str | None]:
    """Process *tasks* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_process_file_tuple, tasks)

        if method == "starmap":
            return pool.starmap(process_file, tasks)

        if method == "imap_unordered":
            return list(pool.imap_unordered(_process_file_tuple, tasks))

        if method == "apply_async":
            async_results: list[AsyncResult[str | None]] = [
                pool.apply_async(_process_file_tuple, (task,)) for task in tasks
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def process_directory(cwd: Path, pool_method: str = "map") -> None:
    """Make eligible files under *cwd* executable and log each change."""
    files: list[Path] = [
        p
        for p in cwd.rglob("*")
        if p.is_file() and ".git" not in p.parts and not p.is_symlink()
    ]

    if not files:
        logger.info("No files to process.")
        return

    tasks: list[tuple[Path, Path]] = [(f, cwd) for f in files]
    results = _run_pool(tasks, pool_method)

    for result in results:
        if result:
            logger.info(result)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for processing.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method

    process_directory(Path.cwd(), pool_method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
