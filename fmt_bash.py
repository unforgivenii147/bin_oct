#!/data/data/com.termux/files/home/.local/bin/python
"""Format shell scripts under CWD with shfmt -w.

Behavior:
  * If exactly one file path is given on the command line, format it directly
    (no multiprocessing Pool). The file does NOT need a ``.sh`` extension or a
    shebang -- it is treated as a shell script as long as it is not binary.
  * Otherwise, collect shell files under CWD (``*.sh`` files plus extension-less
    files whose first 256 bytes start with a bash/sh shebang), skip binaries via
    ``dh.is_binary``, and run ``shfmt -w`` on each using a fixed 8-worker
    ``multiprocessing.Pool`` selected by ``--pool-method``
    (starmap by default, plus map, imap_unordered, apply_async).
  * Log progress and list failures with loguru.
  * Optionally move failed files into an ``error`` subdirectory under CWD via -m/--move.
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

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

POOL_WORKERS: Final[int] = 8

# Pool methods supported by :func:`_run_pool`. ``starmap`` is the default.
POOL_METHODS: Final[tuple[str, ...]] = (
    "starmap",
    "map",
    "imap_unordered",
    "apply_async",
)

# Number of bytes read to detect a shell shebang when the file has no suffix.
SHEBANG_READ_BYTES: Final[int] = 256

# Name of the subdirectory used by ``--move`` to quarantine failed files.
ERROR_DIR_NAME: Final[str] = "error"

# Result of formatting a single file: ``(success, path_as_string)``.
FormatResult: TypeAlias = tuple[bool, str]


# ---------------------------------------------------------------------------
# File classification helpers
# ---------------------------------------------------------------------------


def has_shell_shebang(path: Path) -> bool:
    """Return True when *path* begins with a bash/sh shebang line."""
    try:
        # Read only the first line, capped at SHEBANG_READ_BYTES, so we do not
        # touch the whole file just to detect the interpreter.
        with path.open("rb") as f:
            first = (
                f.readline(SHEBANG_READ_BYTES).decode("utf-8", errors="ignore").strip()
            )
        return first.startswith("#!") and ("bash" in first or "sh" in first)
    except OSError:
        # Unreadable file: be conservative and report "no shebang".
        return False


def is_shell_file(path: Path) -> bool:
    """Return True when *path* qualifies as a shell file for the CWD scan.

    A file qualifies when it is a regular file, is not binary, and either:
      * has a ``.sh`` suffix, or
      * has no suffix and starts with a bash/sh shebang.
    """
    if not path.is_file():
        return False
    if path.suffix == ".sh" or (not path.suffix and has_shell_shebang(path)):
        return not is_binary(path)
    return False


def is_formattable_file(path: Path) -> bool:
    """Return True when *path* can be handed to ``shfmt`` explicitly.

    Unlike :func:`is_shell_file`, this does NOT require a ``.sh`` suffix or a
    shebang. Used for the single-file fast path where the user has explicitly
    named the target, so we trust their intent and only guard against binaries.
    """
    if not path.is_file():
        return False
    return not is_binary(path)


# ---------------------------------------------------------------------------
# Worker function
# ---------------------------------------------------------------------------


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
    """Tuple-argument wrapper around :func:`process_file` for ``Pool.map``.

    ``Pool.map`` only passes a single positional argument, so we wrap the path
    in a 1-tuple and unwrap it here.
    """
    return process_file(item[0])


# ---------------------------------------------------------------------------
# Pool dispatch
# ---------------------------------------------------------------------------


def _run_pool(paths: Sequence[str], method: str) -> list[FormatResult]:
    """Format *paths* with a fixed 8-worker Pool using *method*.

    ``starmap`` is the default and expects 1-tuples of ``(path,)``; the other
    methods are kept for parity / benchmarking.
    """
    with Pool(processes=POOL_WORKERS) as pool:
        if method == "starmap":
            # starmap unpacks each tuple as positional args -> process_file(p)
            return pool.starmap(process_file, [(p,) for p in paths])

        if method == "map":
            # map passes the whole tuple as a single arg -> unwrap in wrapper
            return pool.map(_process_file_tuple, [(p,) for p in paths])

        if method == "imap_unordered":
            # Same calling convention as map, but results arrive out of order.
            return list(pool.imap_unordered(_process_file_tuple, [(p,) for p in paths]))

        if method == "apply_async":
            # Fire off every task, then collect results in submission order.
            async_results: list[AsyncResult[FormatResult]] = [
                pool.apply_async(_process_file_tuple, ((p,),)) for p in paths
            ]
            return [result.get() for result in async_results]

    # Defensive: argparse choices should prevent this, but guard anyway.
    raise ValueError(f"Unsupported pool method: {method}")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def collect_shell_files(cwd: Path) -> list[Path]:
    """Return non-binary shell files under *cwd* (``*.sh`` or shebang-based)."""
    files = [
        p
        for p in get_files(cwd)
        if (not p.suffix and has_shell_shebang(p)) or p.suffix == ".sh"
    ]
    # Second pass: drop binaries that slipped past the suffix/shebang filter.
    return [p for p in files if not is_binary(p)]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def move_failed_files(failed: Sequence[Path], cwd: Path) -> list[Path]:
    """Move *failed* files into ``cwd/error``; return the moved destination paths.

    Files already located inside the error directory are skipped. Missing source
    files are skipped with a warning. Name collisions are resolved by appending
    a numeric suffix (``name.1.sh``, ``name.2.sh``, ...).
    """
    error_dir: Path = cwd / ERROR_DIR_NAME
    error_dir.mkdir(exist_ok=True)

    moved: list[Path] = []
    for src in failed:
        # Resolve defensively -- resolve() can fail on broken symlinks etc.
        try:
            src_resolved = src.resolve()
        except OSError:
            src_resolved = src

        # Skip anything already inside the error directory.
        if error_dir.resolve() in src_resolved.parents:
            logger.warning(f"Skipping move (already in error dir): {src}")
            continue

        # Skip missing files.
        if not src.exists():
            logger.warning(f"Skipping move (missing): {src}")
            continue

        # Pick a non-colliding destination name.
        dest: Path = error_dir / src.name
        if dest.exists():
            stem: str = src.stem
            suffix: str = src.suffix
            counter: int = 1
            while dest.exists():
                dest = error_dir / f"{stem}.{counter}{suffix}"
                counter += 1

        # Perform the move.
        try:
            shutil.move(str(src), str(dest))
            logger.info(f"Moved to error dir: {src} -> {dest}")
            moved.append(dest)
        except OSError as exc:
            logger.error(f"Failed to move {src} to {dest}: {exc}")

    return moved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)

    # Optional positional path(s). If exactly one is given, we format it
    # directly without spinning up a Pool.
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional file(s) to format. A single file is formatted directly "
        "(no Pool); the file does not need a .sh extension. If omitted, "
        "shell files under CWD are used.",
    )

    # Pool method (starmap is the default).
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="starmap",
        help="Multiprocessing pool method to use for formatting (default: starmap).",
    )

    # Optional quarantine-on-failure flag.
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help=f"Move files that failed formatting into the '{ERROR_DIR_NAME}' "
        f"subdirectory under CWD.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point."""
    args: argparse.Namespace = parse_args()
    pool_method: str = args.pool_method
    move_errors: bool = args.move

    cwd: Path = Path.cwd()

    # --- Fast path: exactly one explicit file -> no Pool ------------------
    if len(args.paths) == 1:
        single = Path(args.paths[0])
        # No .sh suffix requirement here -- trust the user's explicit choice,
        # only guard against non-existent / binary files.
        if not is_formattable_file(single):
            logger.warning(
                f"Not a formattable file (missing or binary), skipping: {single}"
            )
            return 0

        logger.info(f"Single file mode: formatting {single.name} directly.")
        success, p_str = process_file(str(single))

        if not success:
            # Normalize to a CWD-relative path for consistent reporting.
            failed_path = Path(p_str)
            try:
                failed_path = failed_path.relative_to(cwd)
            except ValueError:
                pass

            if move_errors:
                move_failed_files([failed_path], cwd)

        return 0

    # --- Multi-file path: discover targets ---------------------------------
    if args.paths:
        # User provided multiple paths: keep the ones that look like shell
        # files (suffix / shebang / non-binary).
        non_binary_files: list[Path] = [
            Path(p) for p in args.paths if is_shell_file(Path(p))
        ]
    else:
        # No paths given: scan CWD for shell files.
        non_binary_files = collect_shell_files(cwd)

    if not non_binary_files:
        logger.warning("No shell files found to format.")
        return 0

    # --- Dispatch to the Pool ---------------------------------------------
    file_strings: list[str] = [str(f) for f in non_binary_files]
    logger.info(f"Processing {len(file_strings)} files...")

    results: list[FormatResult] = _run_pool(file_strings, pool_method)

    # --- Collect and report failures --------------------------------------
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
