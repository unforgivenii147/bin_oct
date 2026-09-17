#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that archives the current directory into a
tar.xz file in the parent directory, using multiprocessing.Pool with 8
workers for concurrency, loguru for logging, pathlib for paths, full type
annotations, and docstrings on every function/class. The script should remove the original directory,
and exit with an error if anything fails.
"""

from __future__ import annotations

import io
import multiprocessing
import os
import shutil
import sys
import tarfile
from collections.abc import Iterable
from multiprocessing.pool import Pool
from pathlib import Path
from typing import List, Tuple

from loguru import logger

# Number of worker processes used for concurrent compression.
WORKERS: int = 8

# Suffix used for the produced archive.
ARCHIVE_SUFFIX: str = ".tar.xz"


def find_files(root: Path) -> list[Path]:
    """
    Recursively find all regular files under ``root``.

    Parameters
    ----------
    root : Path
        Directory to search for files.

    Returns
    -------
    List[Path]
        A list of absolute paths to regular files found under ``root``.

    Raises
    ------
    FileNotFoundError
        If ``root`` does not exist or is not a directory.
    """
    if not root.exists():
        raise FileNotFoundError(f"Root directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root path is not a directory: {root}")

    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for name in filenames:
            candidate = base / name
            # Skip broken symlinks and non-regular files.
            if candidate.is_file() and not candidate.is_symlink():
                files.append(candidate)
            elif candidate.is_symlink() and not candidate.exists():
                logger.warning(f"Skipping broken symlink: {candidate}")
    return files


def _read_file(path: Path) -> tuple[Path, bytes]:
    """
    Read the contents of a file into memory.

    This helper is designed to be executed inside worker processes.

    Parameters
    ----------
    path : Path
        Path of the file to read.

    Returns
    -------
    Tuple[Path, bytes]
        The original path and its raw bytes.

    Raises
    ------
    OSError
        If the file cannot be read.
    """
    return path, path.read_bytes()


def compress_files(files: Iterable[Path]) -> list[tuple[Path, bytes]]:
    """
    Compress file contents concurrently using a multiprocessing pool.

    Each worker reads a file into memory; the result is returned to the
    parent process, which is responsible for writing it into the archive.
    This avoids interleaving writes to the same tar stream.

    Parameters
    ----------
    files : Iterable[Path]
        Paths of the files to read.

    Returns
    -------
    List[Tuple[Path, bytes]]
        A list of ``(path, content)`` tuples.

    Raises
    ------
    Exception
        Any exception raised by a worker is propagated to the caller.
    """
    file_list: list[Path] = list(files)
    if not file_list:
        return []

    print(f"Reading {len(file_list)} file(s) with {WORKERS} workers")
    with Pool(processes=WORKERS) as pool:
        results: list[tuple[Path, bytes]] = pool.map(_read_file, file_list)
    return results


def build_archive(
    archive_path: Path,
    root: Path,
    payload: list[tuple[Path, bytes]],
) -> None:
    """
    Write a ``tar.xz`` archive containing the given file payload.

    Every member name is prefixed with ``root.name`` so that extracting
    the archive recreates the original top-level directory.

    Parameters
    ----------
    archive_path : Path
        Destination path of the ``.tar.xz`` archive.
    root : Path
        Directory that the archived paths are made relative to. Its
        basename is used as the top-level directory inside the archive.
    payload : List[Tuple[Path, bytes]]
        List of ``(path, content)`` tuples to write into the archive.

    Raises
    ------
    OSError
        If the archive cannot be created or written.
    """
    print(f"Writing archive: {archive_path}")
    top_level = root.name  # e.g. "myproject"

    with tarfile.open(
        name=str(archive_path),
        mode="w:xz",
        preset=6,
        format=tarfile.PAX_FORMAT,
    ) as tar:
        for path, content in payload:
            try:
                rel = path.relative_to(root)
            except ValueError:
                # Fallback if the path is somehow outside ``root``.
                rel = Path(path.name)

            # Prefix with the top-level directory name so extraction
            # recreates ``root.name/...``.
            arcname = Path(top_level) / rel

            info = tarfile.TarInfo(name=str(arcname))
            info.size = len(content)
            info.mtime = path.stat().st_mtime
            tar.addfile(info, io.BytesIO(content))

    logger.success(f"Archive created: {archive_path}")


def remove_directory(root: Path) -> None:
    """
    Remove the original directory tree.

    Parameters
    ----------
    root : Path
        Directory to delete.

    Raises
    ------
    OSError
        If the directory cannot be removed.
    """
    print(f"Removing original directory: {root}")
    shutil.rmtree(root)
    logger.success(f"Removed: {root}")


def archive_current_directory() -> Path:
    """
    Archive the current working directory into a ``.tar.xz`` in its parent.

    The archive stores members under a top-level directory equal to the
    basename of the current working directory, so extraction recreates
    that directory.

    Returns
    -------
    Path
        The path of the created archive.

    Raises
    ------
    RuntimeError
        If no files are found, or if any part of the process fails.
    """
    cwd: Path = Path.cwd().resolve()
    parent: Path = cwd.parent
    top_level: str = cwd.name
    archive_path: Path = parent / f"{top_level}{ARCHIVE_SUFFIX}"

    print(f"Current directory: {cwd}")
    print(f"Target archive:    {archive_path}")

    if archive_path.exists():
        raise RuntimeError(f"Archive already exists: {archive_path}")

    files = find_files(cwd)
    if not files:
        raise RuntimeError(f"No files found to archive in: {cwd}")

    payload = compress_files(files)
    build_archive(archive_path, cwd, payload)

    # Verify the archive before deleting the source.
    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        raise RuntimeError(f"Archive verification failed: {archive_path}")

    with tarfile.open(archive_path, mode="r:xz") as tar:
        members = tar.getnames()

    # Every member should live under the top-level directory.
    expected_prefix = f"{top_level}/"
    unexpected = [m for m in members if not m.startswith(expected_prefix)]
    if unexpected:
        raise RuntimeError(
            f"Archive contains members outside '{expected_prefix}': {unexpected[:5]}"
        )

    if len(members) != len(files):
        raise RuntimeError(
            f"Archive member count mismatch: expected {len(files)}, "
            f"found {len(members)}"
        )

    os.chdir(parent)
    remove_directory(cwd)
    return archive_path


def main() -> int:
    """
    Entry point for the archiving script.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
    )

    try:
        archive = archive_current_directory()
    except Exception as exc:  # noqa: BLE001 - top-level safety net.
        logger.exception(f"Archiving failed: {exc}")
        return 1

    logger.success(f"Done. Archive: {archive}")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
