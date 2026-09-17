#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that checks Python files for syntax errors and moves
invalid ones into per-directory ``error`` folders.

The script should:
- Accept file and directory paths as positional CLI arguments, defaulting to
  the current working directory when none are supplied.
- Recursively discover ``.py`` files using a helper ``get_pyfiles`` imported
  from a module named ``dh``.
- Validate each file's syntax with ``ast.parse`` (reading as UTF-8).
- On failure, copy the offending file into an ``error`` subdirectory next to
  it, disambiguating name collisions with a numeric suffix.
- Support a ``--dry-run/-n`` flag that reports intended actions without
  touching the filesystem.
- Use ``loguru`` for all logging output.
- Use ``pathlib.Path`` exclusively for filesystem operations.
- Use ``multiprocessing.Pool.apply_async`` with a fixed pool of 8 workers to
  process files concurrently, with no CLI options controlling parallelism.
- Include complete, strict type hints and docstrings on all functions.
- Provide a ``main()`` entry point returning an integer exit code.
"""

from __future__ import annotations

import argparse
import ast
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

from dh import get_pyfiles
from loguru import logger

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

POOL_SIZE: Final[int] = 8
"""Fixed number of worker processes used for concurrent file processing."""

ERROR_DIR_NAME: Final[str] = "error"
"""Name of the subdirectory where invalid Python files are copied."""


# ---------------------------------------------------------------------------
# Worker function
# ---------------------------------------------------------------------------


def process_file(args: tuple[Path, int, int, bool]) -> None:
    """Validate a single Python file and relocate it if it is invalid.

    The file is parsed with :func:`ast.parse`. If parsing fails, the file is
    copied into an ``error`` directory alongside the original file (creating
    the directory if needed). Name collisions are resolved by appending an
    incrementing numeric suffix.

    Args:
        args: A tuple of ``(path, counter, total, dry_run)`` where ``path`` is
            the file to check, ``counter`` is its 1-based index within the
            batch, ``total`` is the total number of files, and ``dry_run``
            indicates whether filesystem changes should be suppressed.
    """
    path, counter, total, dry_run = args
    path = Path(path)
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}[{counter}/{total}] {path.name}")

    try:
        content: str = path.read_text(encoding="utf-8")
        ast.parse(content)
        if dry_run:
            print(f"  ✅ {path.name} - Valid Python syntax")
        return
    except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as e:
        error_dir: Path = path.parent / ERROR_DIR_NAME
        new_path: Path = error_dir / path.name

        if dry_run:
            print(f"  🔍 Would move to: {new_path} | Error: {e}")
            return

        error_dir.mkdir(exist_ok=True)
        if new_path.exists():
            base: str = path.stem
            ext: str = path.suffix
            idx: int = 1
            while new_path.exists():
                new_path = error_dir / f"{base}_{idx}{ext}"
                idx += 1

        try:
            raw: bytes = path.read_bytes()
            new_path.write_bytes(raw)
            logger.warning(f"  ⚠️  copied to: {new_path} | Error: {e}")
        except OSError as move_error:
            logger.error(f"  ❌ Failed to move {path}: {move_error}")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def get_files_to_process(paths: list[str]) -> list[Path]:
    """Collect a de-duplicated list of Python files to process.

    Args:
        paths: File or directory path strings supplied on the command line.
            When empty, the current working directory is scanned.

    Returns:
        A list of unique :class:`Path` objects pointing at ``.py`` files.
    """
    files: list[Path] = []
    if paths:
        for path_str in paths:
            p: Path = Path(path_str)
            if p.is_file() and p.suffix == ".py":
                files.append(p)
            elif p.is_dir():
                files.extend(get_pyfiles(p))
            else:
                logger.warning(f"⚠️  Skipping: {path_str} (not a .py file or directory)")
    else:
        files = get_pyfiles(Path.cwd())

    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in files:
        resolved: Path = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)
    return unique_files


# ---------------------------------------------------------------------------
# Concurrency driver
# ---------------------------------------------------------------------------


def process_files(files: list[Path], dry_run: bool = False) -> None:
    """Process every file concurrently using a fixed pool of workers.

    Args:
        files: The Python files to check.
        dry_run: When ``True``, no files are copied or moved.
    """
    total: int = len(files)
    if total == 0:
        return

    args_list: list[tuple[Path, int, int, bool]] = [
        (path, idx, total, dry_run) for idx, path in enumerate(files, 1)
    ]

    with Pool(processes=POOL_SIZE) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_file, (arg,)) for arg in args_list
        ]
        for result in async_results:
            try:
                result.get()
            except Exception as e:  # noqa: BLE001
                logger.error(f"  ❌ Unexpected error in worker: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Check Python files for syntax errors and move invalid ones "
            "to 'error' directories"
        ),
        epilog="Example: python script.py --dry-run /path/to/project",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without actually moving files",
    )
    return parser


def main() -> int:
    """Run the syntax-checking CLI.

    Returns:
        An integer exit status: ``0`` on success, ``1`` on failure or
        interruption.
    """
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    try:
        files: list[Path] = get_files_to_process(args.paths)
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Error collecting files: {e}")
        return 1

    if not files:
        print("ℹ️  No Python files found to process.")
        return 0

    print(f"📁 Found {len(files)} Python file(s) to process")
    if args.dry_run:
        print("🔍 DRY RUN MODE - No files will be moved")
        print("-" * 40)

    try:
        process_files(files, dry_run=bool(args.dry_run))
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Interrupted by user")
        return 1
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Error processing files: {e}")
        return 1

    if args.dry_run:
        print("-" * 40)
        print("🔍 DRY RUN COMPLETE - No files were moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
