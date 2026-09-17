#!/data/data/com.termux/files/home/.local/bin/python
"""Implement a Python `tree` command: walk a directory with a multiprocessing pool of 8 workers, optionally show sizes, filter directories, format sizes human-readably, and log via loguru."""

import argparse
import sys
from collections.abc import Iterator
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final

from loguru import logger

from dh import fsz, gsz  # type: ignore[import-untyped]

MAX_WORKERS: Final[int] = 8


def _process_entry(entry: Path) -> tuple[Path, bool]:
    """Return the given path paired with whether it points to a directory."""
    return (entry, entry.is_dir())


def walk_filesystem(root: Path) -> Iterator[tuple[Path, bool]]:
    """Yield ``(entry, is_dir)`` pairs for all non-hidden entries under ``root``.

    Entries whose name starts with ``.`` or that live inside a ``.git``
    directory are skipped. Directory detection runs in a multiprocessing pool
    of :data:`MAX_WORKERS` workers.
    """
    paths: list[Path] = [
        entry
        for entry in root.rglob("*")
        if not entry.name.startswith(".") and ".git" not in entry.parts
    ]

    with Pool(processes=MAX_WORKERS) as pool:
        for entry, is_dir in pool.imap_unordered(_process_entry, paths):
            yield entry, is_dir


def tree(
    root: Path,
    show_sizes: bool = False,
    dirs_only: bool = False,
    human_readable: bool = False,
) -> None:
    """Log a tree view of ``root``, optionally showing sizes and filtering directories."""
    entries: list[tuple[Path, bool]] = sorted(
        walk_filesystem(root), key=lambda x: (not x[1], x[0])
    )

    def print_entry(entry: Path, is_dir: bool, prefix: str = "") -> None:
        """Log a single tree entry, appending size information when requested."""
        if dirs_only and not is_dir:
            return

        size_str: str = ""
        if show_sizes:
            size: int = gsz(entry) if is_dir else entry.stat().st_size
            size_str = f" [{fsz(size) if human_readable else size}]"

        connector: str = "└── " if prefix else ""
        logger.info(f"{prefix}{connector}{entry.name}{size_str}")

    for entry, is_dir in entries:
        if entry == root:
            logger.info(entry.name)
            continue

        parts: list[str] = list(entry.relative_to(root).parts)
        prefix: str = ""
        for i, _part in enumerate(parts[:-1]):
            prefix += "    " if i == len(parts) - 2 else "│   "
        print_entry(entry, is_dir, prefix)


def main() -> None:
    """Parse CLI arguments and run the tree command."""
    parser = argparse.ArgumentParser(description="Python tree command implementation")
    parser.add_argument(
        "directory", nargs="?", default=".", help="Directory to traverse"
    )
    parser.add_argument("-s", "--sizes", action="store_true", help="Show sizes")
    parser.add_argument(
        "-d", "--dirs-only", action="store_true", help="List directories only"
    )
    parser.add_argument(
        "-H", "--human-readable", action="store_true", help="Human-readable sizes"
    )

    args: argparse.Namespace = parser.parse_args()
    root: Path = Path(args.directory).resolve()

    if not root.exists():
        logger.error("Error: {} does not exist", root)
        sys.exit(1)

    tree(root, args.sizes, args.dirs_only, args.human_readable)


if __name__ == "__main__":
    raise SystemExit(main())
