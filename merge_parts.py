#!/data/data/com.termux/files/home/.local/bin/python
"""Merge ``<prefix>.part<N>`` files into their reassembled ``<prefix>`` outputs.

Regenerate this script: parse CLI paths (files or directories, default CWD) with pathlib, match
filenames against ``^(?P<prefix>.+)\\.part(?P<num>\\d+)$``, group parts by (parent, prefix), sort by
part number, concatenate bytes into ``<prefix>`` using a fixed 8-worker multiprocessing Pool selected
by --pool-method (map, starmap, imap_unordered, apply_async), and log results with loguru.
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

PART_RE: Final[re.Pattern[str]] = re.compile(r"^(?P<prefix>.+)\.part(?P<num>\d+)$")
READ_CHUNK: Final[int] = 1024 * 1024

GroupKey: TypeAlias = tuple[Path, str]
GroupItems: TypeAlias = list[tuple[int, Path]]
GroupedParts: TypeAlias = dict[GroupKey, GroupItems]
GroupEntry: TypeAlias = tuple[GroupKey, GroupItems]


def collect_paths(inputs: Sequence[str]) -> list[Path]:
    """Collect candidate files from *inputs* (or CWD when empty)."""
    if not inputs:
        return [
            p for p in Path(".").rglob("*") if p.is_file() and PART_RE.match(p.name)
        ]

    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            out.extend(x for x in p.rglob("*") if x.is_file() and PART_RE.match(x.name))
        elif p.is_file():
            out.append(p)
    return out


def group_parts(paths: Sequence[Path]) -> GroupedParts:
    """Group *paths* into ``{(parent, prefix): [(num, path), ...]}``."""
    groups: GroupedParts = {}
    for p in paths:
        m = PART_RE.match(p.name)
        if not m:
            continue
        key: GroupKey = (p.parent.resolve(), m.group("prefix"))
        groups.setdefault(key, []).append((int(m.group("num")), p))
    return groups


def merge_group(items: GroupEntry) -> Path:
    """Concatenate a group's numbered part files into the reassembled output path."""
    (parent, prefix), parts = items
    parts.sort(key=lambda x: x[0])
    out = parent / prefix
    with out.open("wb") as dst:
        for _, part in parts:
            with part.open("rb") as src:
                for chunk in iter(lambda: src.read(READ_CHUNK), b""):
                    dst.write(chunk)
    return out


def _merge_group_tuple(item: tuple[GroupEntry]) -> Path:
    """Tuple-argument wrapper around :func:`merge_group` for ``Pool.map``."""
    return merge_group(item[0])


def _run_pool(entries: Sequence[GroupEntry], method: str) -> list[Path]:
    """Merge *entries* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_merge_group_tuple, [(entry,) for entry in entries])

        if method == "starmap":
            return pool.starmap(merge_group, [(entry,) for entry in entries])

        if method == "imap_unordered":
            return list(
                pool.imap_unordered(_merge_group_tuple, [(entry,) for entry in entries])
            )

        if method == "apply_async":
            async_results: list[AsyncResult[Path]] = [
                pool.apply_async(merge_group, (entry,)) for entry in entries
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to scan; defaults to CWD.",
    )
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for merging.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    inputs: list[str] = list(args.paths)

    paths = collect_paths(inputs)
    groups = group_parts(paths)
    if not groups:
        logger.error("No .part files found")
        return 1

    outputs = _run_pool(list(groups.items()), pool_method)
    for out in outputs:
        logger.info(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
