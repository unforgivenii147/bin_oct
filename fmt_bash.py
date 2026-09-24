#!/data/data/com.termux/files/home/.local/bin/python
"""Format shell scripts under CWD with shfmt -w.

Regenerate this script: collect files via dh.get_files under CWD, keep ``*.sh`` files and extension-less
files whose first 256 bytes start with a shell shebang (bash/sh), skip binaries via dh.is_binary, then
run ``shfmt -w`` on each using a fixed 8-worker multiprocessing Pool selected by --pool-method
(map, starmap, imap_unordered, apply_async); log progress and list failures with loguru.
Optionally move failed files into an ``error`` subdirectory under CWD via -m/--move.
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, TypeAlias

from dh import get_files, is_binary, runcmd  # type: ignore[import-untyped]
from loguru import logger

POOL_WORKERS: Final[int] = 8
POOL_METHODS: Final[tuple[str, ...]] = (
    "map",
    "starmap",
    "imap_unordered",
    "apply_async",
)

SHEBANG_READ_BYTES: Final[int] = 256
ERROR_DIR_NAME: Final[str] = "error"

FormatResult: TypeAlias = tuple[bool, str]


def has_shell_shebang(path: Path) -> bool:
    """Return True when *path* begins with a bash/sh shebang line."""
    try:
        with path.open("rb") as f:
            first = (
                f.readline(SHEBANG_READ_BYTES).decode("utf-8", errors="ignore").strip()
            )
        return first.startswith("#!") and ("bash" in first or "sh" in first)
    except OSError:
        return False


def process_file(path_str: str) -> FormatResult:
    """Run ``shfmt -w`` on *path_str*; return ``(success, path_str)``."""
    path = Path(path_str)
    logger.info(f"Formatting:  {path.name}")

    res_code, _, stderr = runcmd(["shfmt", "-w", str(path)], show_output=True)
    if res_code != 0:
        logger.error(f"shfmt failed on {path.name}: {stderr.strip()}")
        return (False, path_str)
    return (True, path_str)


def _process_file_tuple(item: tuple[str]) -> FormatResult:
    """Tuple-argument wrapper around :func:`process_file` for ``Pool.map``."""
    return process_file(item[0])


def _run_pool(paths: Sequence[str], method: str) -> list[FormatResult]:
    """Format *paths* with a fixed 8-worker Pool using *method*."""
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "map":
            return pool.map(_process_file_tuple, [(p,) for p in paths])

        if method == "starmap":
            return pool.starmap(process_file, [(p,) for p in paths])

        if method == "imap_unordered":
            return list(pool.imap_unordered(_process_file_tuple, [(p,) for p in paths]))

        if method == "apply_async":
            async_results: list[AsyncResult[FormatResult]] = [
                pool.apply_async(_process_file_tuple, ((p,),)) for p in paths
            ]
            return [result.get() for result in async_results]

    raise ValueError(f"Unsupported pool method: {method}")


def collect_shell_files(cwd: Path) -> list[Path]:
    """Return non-binary shell files under *cwd* (``*.sh`` or shebang-based)."""
    files = [
        p
        for p in get_files(cwd)
        if (not p.suffix and has_shell_shebang(p)) or p.suffix == ".sh"
    ]
    return [p for p in files if not is_binary(p)]


def move_failed_files(failed: Sequence[Path], cwd: Path) -> list[Path]:
    """Move *failed* files into ``cwd/error``; return the moved destination paths.

    Files already located inside the error directory are skipped. Missing source
    files are skipped with a warning. Name collisions are resolved by appending
    a numeric suffix.
    """
    error_dir: Path = cwd / ERROR_DIR_NAME
    error_dir.mkdir(exist_ok=True)

    moved: list[Path] = []
    for src in failed:
        try:
            src_resolved = src.resolve()
        except OSError:
            src_resolved = src

        if error_dir.resolve() in src_resolved.parents:
            logger.warning(f"Skipping move (already in error dir): {src}")
            continue

        if not src.exists():
            logger.warning(f"Skipping move (missing): {src}")
            continue

        dest: Path = error_dir / src.name
        if dest.exists():
            stem: str = src.stem
            suffix: str = src.suffix
            counter: int = 1
            while dest.exists():
                dest = error_dir / f"{stem}.{counter}{suffix}"
                counter += 1

        try:
            shutil.move(str(src), str(dest))
            logger.info(f"Moved to error dir: {src} -> {dest}")
            moved.append(dest)
        except OSError as exc:
            logger.error(f"Failed to move {src} to {dest}: {exc}")

    return moved


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="map",
        help="Multiprocessing pool method to use for formatting.",
    )
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help=f"Move files that failed formatting into the '{ERROR_DIR_NAME}' subdirectory under CWD.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    move_errors: bool = args.move

    cwd: Path = Path.cwd()
    non_binary_files: list[Path] = collect_shell_files(cwd)
    if not non_binary_files:
        logger.warning("No shell files found to format.")
        return 0

    file_strings: list[str] = [str(f) for f in non_binary_files]
    logger.info(f"Processing {len(file_strings)} files...")

    results: list[FormatResult] = _run_pool(file_strings, pool_method)
    failed: list[Path] = []
    for success, p_str in results:
        if not success:
            try:
                failed.append(Path(p_str).relative_to(cwd))
            except ValueError:
                failed.append(Path(p_str))

    if failed:
        logger.warning("Failed files:")
        for f in failed:
            logger.warning(f"  - {f}")

        if move_errors:
            move_failed_files(failed, cwd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
