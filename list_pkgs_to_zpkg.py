#!/data/data/com.termux/files/home/.local/bin/python
"""List installed pure-Python user-site packages that expose exactly one top-level module.

Regenerate this script: iterate importlib.metadata.distributions(), extract DistInfo (name, location,
files, top_level) from each, evaluate eligibility (pure-Python, no "-"/"_" in name, located under
~/.local/lib, exactly one top-level module) using a fixed 8-worker multiprocessing Pool selected by
--pool-method (map, starmap, imap_unordered, apply_async), sort names case-insensitively, and write them
to ~/list.txt, logging with loguru.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import Distribution, distributions
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, NamedTuple

from loguru import logger

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

NATIVE_SUFFIXES: Final[frozenset[str]] = frozenset({".so", ".pyd", ".dylib"})
OUTPUT_PATH: Final[Path] = Path.home() / "list.txt"


class DistInfo(NamedTuple):
    """Picklable snapshot of a :class:`Distribution` used inside worker processes."""

    name: str
    location: Path
    files: tuple[Path, ...] | None
    top_level: tuple[str, ...] | None


def extract_dist_info(dist: Distribution) -> DistInfo | None:
    """Return a picklable :class:`DistInfo` from *dist*, or ``None`` on failure."""
    try:
        location = Path(str(dist.locate_file(""))).resolve()
    except Exception:  # noqa: BLE001
        return None

    files: tuple[Path, ...] | None = None
    try:
        if dist.files is not None:
            files = tuple(dist.files)
    except Exception:  # noqa: BLE001
        files = None

    top_level_text: str | None
    try:
        top_level_text = dist.read_text("top_level.txt")
    except (FileNotFoundError, TypeError):
        top_level_text = None

    top_level: tuple[str, ...] | None = None
    if top_level_text:
        top_level = tuple(
            line.strip() for line in top_level_text.splitlines() if line.strip()
        )

    return DistInfo(
        name=dist.name,
        location=location,
        files=files,
        top_level=top_level,
    )


def is_pure_python(info: DistInfo) -> bool:
    """Return True when *info* declares no compiled-extension files."""
    if info.files is None:
        return False
    return not any(f.suffix in NATIVE_SUFFIXES for f in info.files)


def has_valid_name(name: str) -> bool:
    """Return True when *name* contains neither ``-`` nor ``_``."""
    return "-" not in name and "_" not in name


def get_top_level_modules(info: DistInfo) -> set[str]:
    """Return the set of top-level module names exposed by *info*."""
    if info.top_level:
        return set(info.top_level)

    if info.files:
        top_levels: set[str] = set()
        for file in info.files:
            parts = file.parts
            if parts and not parts[0].endswith(".dist-info"):
                top_levels.add(parts[0])
        return top_levels

    return set()


def is_user_site(location: Path) -> bool:
    """Return True when *location* is inside the user site directory."""
    user_site = Path.home() / ".local" / "lib"
    try:
        return str(user_site) in str(location)
    except Exception:  # noqa: BLE001
        return False


def check_package(info: DistInfo) -> str | None:
    """Return the package name when *info* meets all criteria, else ``None``."""
    if not is_pure_python(info):
        return None
    name = info.name.lower()
    if not has_valid_name(name):
        return None
    if not is_user_site(info.location):
        return None
    if len(get_top_level_modules(info)) != 1:
        return None
    return info.name


def _check_package_tuple(item: tuple[DistInfo, ...]) -> str | None:
    """Tuple-argument wrapper around :func:`check_package` for ``Pool.map``."""
    return check_package(item[0])


def _run_pool(infos: Sequence[DistInfo], method: str) -> list[str | None]:
    """Evaluate *infos* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(check_package, infos)

        if method == "starmap":
            return pool.starmap(check_package, [(info,) for info in infos])

        if method == "imap_unordered":
            return list(pool.imap_unordered(check_package, infos))

        if method == "apply_async":
            async_results: list[AsyncResult[str | None]] = [
                pool.apply_async(check_package, (info,)) for info in infos
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for eligibility checks.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method

    infos: list[DistInfo] = []
    for dist in distributions():
        info = extract_dist_info(dist)
        if info is not None:
            infos.append(info)

    raw_results = _run_pool(infos, pool_method)
    results: list[str] = [name for name in raw_results if name is not None]

    if not results:
        logger.warning("No packages found matching criteria.")
        return 0

    results.sort(key=str.lower)
    OUTPUT_PATH.write_text("\n".join(results) + "\n", encoding="utf-8")
    logger.info(f"Saved {len(results)} package names to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
