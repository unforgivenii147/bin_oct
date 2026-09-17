#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that moves Python test files (files whose stem contains "_test" or "test_")
from a base directory into ~/tmp/tests while preserving their relative directory structure, logging
moved files to ~/tmp/moved_files.json and supporting a --reverse flag to undo the operation. The
script must use pathlib for all filesystem paths, multiprocessing.Pool.apply_async with a fixed pool
of 8 workers for concurrency, loguru for logging, complete strict type annotations (mypy/pyright
clean), docstrings on all functions and the module, and argparse for a --reverse flag, --dir base
directory, and --log log path. Clean up empty directories under the destination after a reverse.
"""

from __future__ import annotations

import argparse
import json
import shutil
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger

TESTS_DIR: Path = Path.home() / "tmp" / "tests"
MOVED_FILES_LOG: Path = Path.home() / "tmp" / "moved_files.json"
POOL_WORKERS: int = 8

MoveResult = tuple[str, bool, str]


def is_test_file(path: Path) -> bool:
    """Return True if the file stem looks like a test file.

    Args:
        path: Path to inspect.

    Returns:
        True when the stem contains "_test" or "test_".
    """
    stem: str = path.stem
    return "_test" in stem or "test_" in stem


def get_relative_path(path: Path, base_dir: Path) -> Path:
    """Return path relative to base_dir, falling back to path itself.

    Args:
        path: Path to make relative.
        base_dir: Base directory used for relativity.

    Returns:
        The relative path, or the original path when not under base_dir.
    """
    try:
        return path.relative_to(base_dir)
    except ValueError:
        return path


def move_file(source: Path, dest: Path) -> MoveResult:
    """Move a single file, creating parent directories as needed.

    Args:
        source: File to move.
        dest: Destination path.

    Returns:
        A tuple of (source string, success flag, message).
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return str(source), True, f"Moved to {dest}"
    except Exception as e:  # noqa: BLE001
        return str(source), False, f"Error: {e!s}"


def find_test_files(base_dir: Path) -> list[Path]:
    """Recursively find Python test files under base_dir.

    Args:
        base_dir: Directory to search.

    Returns:
        List of test file paths.
    """
    test_files: list[Path] = []
    for py_file in base_dir.rglob("*.py"):
        if is_test_file(py_file):
            test_files.append(py_file)
    return test_files


def move_files_parallel(
    test_files: list[Path],
    base_dir: Path,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Move test files to TESTS_DIR in parallel using a multiprocessing pool.

    Args:
        test_files: Test files to move.
        base_dir: Base directory used to compute relative destination paths.

    Returns:
        A tuple of (mapping of original->destination, list of (source, message)).
    """
    file_mapping: dict[str, str] = {}
    results: list[tuple[str, str]] = []
    pool: Pool = Pool(processes=POOL_WORKERS)
    try:
        async_results: list[tuple[Any, Path, Path]] = []
        for source_file in test_files:
            relative_path: Path = get_relative_path(source_file, base_dir)
            dest_file: Path = TESTS_DIR / relative_path
            async_result = pool.apply_async(move_file, (source_file, dest_file))
            async_results.append((async_result, source_file, dest_file))

        for async_result, source_file, dest_file in async_results:
            _source_str, success, message = async_result.get()
            if success:
                file_mapping[str(source_file)] = str(dest_file)
                results.append((str(source_file), message))
                logger.success(message)
            else:
                results.append((str(source_file), message))
                logger.error(message)
    finally:
        pool.close()
        pool.join()
    return file_mapping, results


def reverse_move(moved_files_log: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Reverse a previous move operation using the saved log file.

    Args:
        moved_files_log: Path to the JSON log mapping original->moved paths.

    Returns:
        A tuple of (the log mapping, list of (source, message)).

    Raises:
        FileNotFoundError: If the log file does not exist.
    """
    if not moved_files_log.exists():
        raise FileNotFoundError(f"Log file not found: {moved_files_log}")

    with open(moved_files_log) as f:
        file_mapping: dict[str, str] = json.load(f)

    results: list[tuple[str, str]] = []
    pool: Pool = Pool(processes=POOL_WORKERS)
    try:
        async_results: list[tuple[Any, Path, Path]] = []
        for original_path, moved_path in file_mapping.items():
            moved_file: Path = Path(moved_path)
            original_file: Path = Path(original_path)
            if moved_file.exists():
                async_result = pool.apply_async(move_file, (moved_file, original_file))
                async_results.append((async_result, moved_file, original_file))

        for async_result, source_file, _dest_file in async_results:
            _source_str, success, message = async_result.get()
            if success:
                results.append((str(source_file), message))
                logger.success(message)
            else:
                results.append((str(source_file), message))
                logger.error(message)
    finally:
        pool.close()
        pool.join()
    return file_mapping, results


def save_log(file_mapping: dict[str, str], log_path: Path) -> None:
    """Persist the file mapping to a JSON log file.

    Args:
        file_mapping: Mapping of original paths to moved paths.
        log_path: Destination log file path.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(file_mapping, f, indent=2)
    print(f"📋 Log saved to: {log_path}")


def cleanup_empty_dirs(root: Path) -> None:
    """Remove empty directories under root, bottom-up.

    Args:
        root: Root directory to prune.
    """
    try:
        for parent in sorted(root.rglob("*"), reverse=True):
            if parent.is_dir():
                try:
                    if not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    continue
    except OSError:
        pass


def main() -> int:
    """Entry point: parse arguments and dispatch move or reverse.

    Returns:
        Process exit code.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            "Move Python test files to ~/tmp/tests with directory structure "
            "preservation."
        )
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse the move operation (return files to original locations).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Base directory to search for test files (default: current directory).",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=MOVED_FILES_LOG,
        help=f"Path to log file (default: {MOVED_FILES_LOG}).",
    )
    args: argparse.Namespace = parser.parse_args()

    try:
        if args.reverse:
            print(f"🔄 Reversing move operation from log: {args.log}")
            _file_mapping, results = reverse_move(args.log)
            print(f"✅ Reversed {len(results)} files")
            cleanup_empty_dirs(TESTS_DIR)
        else:
            print(f"🔍 Searching for test files in: {args.dir}")
            test_files: list[Path] = find_test_files(args.dir)
            if not test_files:
                logger.warning("❌ No test files found.")
                return 0
            print(f"📦 Found {len(test_files)} test file(s)")
            print(f"📍 Destination: {TESTS_DIR}")
            file_mapping, _results = move_files_parallel(test_files, args.dir)
            save_log(file_mapping, args.log)
            print(f"✅ Moved {len(file_mapping)} file(s)")
    except FileNotFoundError as e:
        logger.error(f"❌ Error: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Unexpected error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
