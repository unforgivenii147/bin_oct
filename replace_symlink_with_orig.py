#!/data/data/com.termux/files/home/.local/bin/python
"""Replace symlinks under the current directory with copies of their targets: scan for symlinks, resolve each in a multiprocessing pool of 8 workers, skip `bin/` siblings and `.so` targets, and log replaced and errored symlinks to `replaced.txt` and `errors.txt` via loguru."""

import shutil
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final, NamedTuple

from loguru import logger

MAX_WORKERS: Final[int] = 8
REPLACED_LOG_NAME: Final[str] = "replaced.txt"
ERRORS_LOG_NAME: Final[str] = "errors.txt"


class ProcessResult(NamedTuple):
    """Outcome of processing one symlink."""

    status: str  # "replaced", "error", or "skipped"
    msg: str


def process_symlink(symlink_path: Path) -> ProcessResult | None:
    """Replace a symlink with a copy of its target.

    Returns ``None`` when the symlink should be skipped (i.e. it lives in a
    ``bin`` directory pointing at a sibling, or its target is a ``.so`` file).
    Otherwise returns a :class:`ProcessResult` describing the outcome.
    """
    try:
        raw_target: Path = symlink_path.readlink()
        target_path: Path = (
            raw_target
            if raw_target.is_absolute()
            else (symlink_path.parent / raw_target).resolve()
        )

        if (
            symlink_path.parent.name == "bin"
            and target_path.parent == symlink_path.parent
        ):
            return None

        if target_path.suffix == ".so":
            return None

        if not target_path.exists():
            return ProcessResult(
                "error",
                f"Target does not exist: {symlink_path} -> {target_path}",
            )

        symlink_path.unlink()
        if target_path.is_dir():
            shutil.copytree(target_path, symlink_path)
        else:
            shutil.copy2(target_path, symlink_path)

        return ProcessResult(
            "replaced",
            f"Replaced: {symlink_path} -> {target_path}",
        )
    except Exception as e:
        return ProcessResult(
            "error",
            f"Failed to process {symlink_path}: {e!s}",
        )


def main() -> None:
    """CLI entry point: scan for symlinks, replace them in parallel, and write logs."""
    current_dir: Path = Path.cwd()
    replaced_log: Path = current_dir / REPLACED_LOG_NAME
    errors_log: Path = current_dir / ERRORS_LOG_NAME

    logger.info("Scanning for symlinks...")
    symlinks: list[Path] = [p for p in current_dir.rglob("*") if p.is_symlink()]

    if not symlinks:
        logger.info("No symlinks found.")
        return

    logger.info("Found {} symlinks. Processing in parallel...", len(symlinks))

    replaced_list: list[str] = []
    errors_list: list[str] = []

    with Pool(processes=MAX_WORKERS) as pool:
        for result in pool.imap_unordered(process_symlink, symlinks):
            if result is None:
                continue
            if result.status == "replaced":
                replaced_list.append(result.msg)
            elif result.status == "error":
                errors_list.append(result.msg)

    if replaced_list:
        replaced_log.write_text("\n".join(replaced_list) + "\n", encoding="utf-8")
        logger.info(
            "Successfully replaced {} symlinks. Logged to {}",
            len(replaced_list),
            REPLACED_LOG_NAME,
        )

    if errors_list:
        errors_log.write_text("\n".join(errors_list) + "\n", encoding="utf-8")
        logger.error(
            "Encountered {} errors. Logged to {}",
            len(errors_list),
            ERRORS_LOG_NAME,
        )


if __name__ == "__main__":
    raise SystemExit(main())
