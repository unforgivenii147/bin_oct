#!/data/data/com.termux/files/home/.local/bin/python
"""Move every `tests` directory out of `~/.local/lib/python3.12/site-packages` into `~/tmp/tests_dirs` while preserving relative structure: discover candidates, process them via `multiprocessing.pool.starmap` on a fixed pool of 8 workers, skip excluded packages, support a `-d` dry-run flag, and log with loguru."""

import shutil
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final, NamedTuple

from loguru import logger

MAX_WORKERS: Final[int] = 8
SRC: Final[Path] = Path.home() / ".local" / "lib" / "python3.12" / "site-packages"
DEST: Final[Path] = Path.home() / "tmp" / "tests_dirs"
EXCLUDED: Final[tuple[str, ...]] = ("numpy", "pandas", "scipy", "numba")
DRY_RUN: Final[bool] = "-d" in sys.argv


class MoveResult(NamedTuple):
    """Outcome of moving a single `tests` directory."""

    path: Path
    success: bool
    message: str


def _is_excluded(path: Path) -> bool:
    """Return ``True`` if ``path`` lies under any package listed in :data:`EXCLUDED`."""
    parts: tuple[str, ...] = path.parts
    return any(name in parts for name in EXCLUDED)


def move_tests_folder(
    tests_path: Path,
    base_src: Path,
    base_dst: Path,
    dry_run: bool = DRY_RUN,
) -> MoveResult:
    """Move one `tests` directory from ``base_src`` into the mirrored ``base_dst`` path.

    Returns a :class:`MoveResult` describing the outcome. When ``dry_run`` is
    ``True`` no filesystem changes are made.
    """
    if _is_excluded(tests_path):
        return MoveResult(tests_path, False, f"excluded path: {tests_path}")

    try:
        relative_path: Path = tests_path.relative_to(base_src)
        dst_path: Path = base_dst / relative_path.parent / tests_path.name

        if dry_run:
            return MoveResult(
                tests_path, True, f"will move: {tests_path} -> {dst_path}"
            )

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tests_path), str(dst_path))
        return MoveResult(tests_path, True, f"moved: {tests_path} -> {dst_path}")
    except Exception as e:
        return MoveResult(tests_path, False, f"error moving {tests_path}: {e}")


def move_tests_recursive(
    source_dir: Path = SRC,
    destination_dir: Path = DEST,
    dry_run: bool = DRY_RUN,
) -> int:
    """Move all `tests` directories discovered under ``source_dir`` in parallel.

    Returns the number of directories successfully moved (or that would be
    moved, when ``dry_run`` is enabled).
    """
    source: Path = source_dir.resolve()
    destination: Path = destination_dir

    tests_folders: list[Path] = [
        p for p in source.rglob("tests") if p.is_dir() and not _is_excluded(p)
    ]

    if not tests_folders:
        logger.info("No 'tests' folders found.")
        return 0

    logger.info("Found {} 'tests' folder(s) to move", len(tests_folders))
    logger.info("Source: {}", source)
    logger.info("Destination: {}", destination)

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[Path, Path, Path, bool]] = [
        (tests_path, source, destination, dry_run) for tests_path in tests_folders
    ]

    moved_count: int = 0
    with Pool(processes=MAX_WORKERS) as pool:
        for result in pool.starmap(move_tests_folder, jobs):
            if result.success:
                logger.info("{}", result.message)
                moved_count += 1
            else:
                logger.warning("{}", result.message)

    logger.info(
        "✓ Successfully moved {}/{} directories",
        moved_count,
        len(tests_folders),
    )
    return moved_count


def main() -> None:
    """CLI entry point."""
    move_tests_recursive()


if __name__ == "__main__":
    raise SystemExit(main())
