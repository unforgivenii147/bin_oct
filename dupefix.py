#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that scans a directory tree for duplicate files
and optionally deletes them.

The generated script should:
- Recursively scan a target root directory (default: current directory).
- Group regular (non-symlink) files by size, then hash only the size groups
  with more than one member using xxhash.xxh64 in 8 KiB chunks.
- Hash files concurrently via multiprocessing.Pool.imap_unordered with a
  fixed pool of 8 workers (no CLI flag controls parallelism).
- Report duplicate groups, retain the oldest file (by mtime, tiebroken by
  path), and either print planned deletions (dry-run) or move the extras to
  the trash via `gio trash` when available, otherwise unlink them.
- Log all progress and outcomes with loguru; use pathlib for all filesystem
  operations; include complete type annotations and docstrings.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import xxhash
from loguru import logger

POOL_SIZE: int = 8
HASH_CHUNK_SIZE: int = 8192
DEFAULT_ROOT: str = "."

FileHashResult = tuple[Path, str | None]


def get_file_hash(filepath: Path) -> FileHashResult:
    """Return the xxh64 hex digest of ``filepath``.

    Args:
        filepath: Path of the file to hash.

    Returns:
        A tuple ``(filepath, digest)`` where ``digest`` is the hex digest, or
        ``None`` if the file is missing or cannot be read.
    """
    try:
        if not filepath.exists():
            return filepath, None
        hasher = xxhash.xxh64()
        with filepath.open("rb") as f:
            while True:
                chunk: bytes = f.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return filepath, hasher.hexdigest()
    except (OSError, PermissionError):
        return filepath, None


def _find_candidates(root: Path) -> list[Path]:
    """Return files whose size is shared by at least one other file.

    Args:
        root: Root directory to scan recursively.

    Returns:
        A list of candidate file paths for content hashing.
    """
    size_map: dict[int, list[Path]] = defaultdict(list)
    path: Path
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                size_map[path.stat().st_size].append(path)
            except OSError:
                continue

    candidates: list[Path] = []
    paths: list[Path]
    for paths in size_map.values():
        if len(paths) > 1:
            candidates.extend(paths)
    return candidates


def _hash_files(files: list[Path]) -> dict[str, list[Path]]:
    """Hash ``files`` in parallel and group paths by digest.

    Args:
        files: Candidate file paths to hash.

    Returns:
        A mapping of hex digest to the list of files sharing that digest.
    """
    hash_map: dict[str, list[Path]] = defaultdict(list)
    if not files:
        return hash_map

    with Pool(processes=POOL_SIZE) as pool:
        result: FileHashResult
        for result in pool.imap_unordered(get_file_hash, files):
            filepath, file_hash = result
            if file_hash:
                hash_map[file_hash].append(filepath)
    return hash_map


def _delete_file(path: Path) -> int | None:
    """Delete or trash ``path`` and return its size in bytes.

    Args:
        path: File to remove.

    Returns:
        The file's size in bytes if it was removed, or ``None`` if the file
        was already gone or could not be removed.
    """
    try:
        if not path.exists():
            return None
        file_size: int = path.stat().st_size
        if shutil.which("gio"):
            subprocess.run(["gio", "trash", str(path)], check=True)
        else:
            path.unlink()
        return file_size
    except OSError as exc:
        logger.error("Error deleting {}: {}", path, exc)
        return None


def remove_duplicates(root_dir: str, dry_run: bool = True) -> None:
    """Find and optionally delete duplicate files under ``root_dir``.

    Args:
        root_dir: Directory to scan recursively.
        dry_run: When ``True``, only report what would be deleted.
    """
    root: Path = Path(root_dir)
    logger.info("Scanning directory tree...")

    files_to_hash: list[Path] = _find_candidates(root)
    logger.info("Hashing {} potential duplicate files...", len(files_to_hash))

    hash_map: dict[str, list[Path]] = _hash_files(files_to_hash)

    total_freed: int = 0
    duplicates_found: int = 0

    file_hash: str
    paths: list[Path]
    for paths in hash_map.values():
        if len(paths) <= 1:
            continue
        duplicates_found += len(paths) - 1
        paths.sort(key=lambda p: (p.stat().st_mtime, str(p)))
        to_delete: list[Path] = paths[1:]
        p: Path
        for p in to_delete:
            try:
                if not p.exists():
                    continue
                file_size: int = p.stat().st_size
                if dry_run:
                    logger.info("Would delete: {} ({} bytes)", p, file_size)
                    total_freed += file_size
                else:
                    freed: int | None = _delete_file(p)
                    if freed is not None:
                        total_freed += freed
                        logger.info("Deleted: {}", p)
            except OSError as exc:
                logger.error("Error deleting {}: {}", p, exc)

    logger.info("Cleanup complete.")
    logger.info("Duplicate files found: {}", duplicates_found)
    if not dry_run:
        logger.info("Total disk space freed: {:.2f} MB", total_freed / (1024 * 1024))
    else:
        logger.info("Potential space to free: {:.2f} MB", total_freed / (1024 * 1024))
        logger.info("Run with dry_run=False to actually delete files.")


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the duplicate-file cleanup script.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    args: list[str] = list(argv) if argv is not None else sys.argv[1:]
    target_dir: str = args[0] if args else DEFAULT_ROOT

    logger.info("DRY RUN - No files will be deleted")
    remove_duplicates(target_dir, dry_run=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
