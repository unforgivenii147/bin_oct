#!/data/data/com.termux/files/home/.local/bin/python
"""Format JS/TS/CSS/HTML/JSON files with Prettier: discover matching files under the current directory, run `prettier --write` on each in a multiprocessing pool of 8 workers, move failures into a sibling `error/` folder, and log progress via loguru."""

import shutil
import subprocess
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final, NamedTuple

from loguru import logger

MAX_WORKERS: Final[int] = 8
PRETTIER_TIMEOUT_SECONDS: Final[int] = 900
ERROR_DIR_NAME: Final[str] = "error"

EXTENSIONS: Final[tuple[str, ...]] = (
    ".js",
    ".css",
    ".html",
    ".json",
    ".mjs",
    ".cjs",
    ".ts",
    ".jsx",
    ".tsx",
    ".tsm",
    ".jsm",
)

EXCLUDE_PATTERNS: Final[tuple[str, ...]] = (
    ".min.js",
    ".min.css",
    ".d.ts",
)


class FormatResult(NamedTuple):
    """Outcome of formatting a single file."""

    path: Path
    success: bool
    error_msg: str | None


def should_format(path: Path) -> bool:
    """Return ``True`` if ``path`` has a supported extension and no excluded suffix."""
    if path.suffix not in EXTENSIONS:
        return False
    return all(not path.name.endswith(p) for p in EXCLUDE_PATTERNS)


def get_files_to_format(cwd: Path) -> list[Path]:
    """Recursively collect all files under ``cwd`` that should be formatted."""
    files: list[Path] = []
    for path in cwd.rglob("*"):
        if path.is_dir():
            continue
        if ERROR_DIR_NAME in path.parts:
            continue
        if should_format(path):
            files.append(path)
    return files


def unique_path(path: Path) -> Path:
    """Return a variant of ``path`` that does not yet exist by appending a counter."""
    if not path.exists():
        return path
    stem: str = path.stem
    suffix: str = path.suffix
    parent: Path = path.parent
    counter: int = 1
    while True:
        candidate: Path = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_to_error_folder(path: Path) -> Path | None:
    """Move ``path`` into a sibling ``error/`` directory and return its new location."""
    error_dir: Path = path.parent / ERROR_DIR_NAME
    error_dir.mkdir(exist_ok=True)
    dest: Path = unique_path(error_dir / path.name)
    try:
        shutil.move(str(path), str(dest))
        return dest
    except Exception as e:
        logger.error("Failed to move {} to {}: {}", path, dest, e)
        return None


def format_file(path: Path) -> FormatResult:
    """Run Prettier on ``path`` and return a :class:`FormatResult`."""
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["prettier", "--write", str(path)],
            capture_output=True,
            text=True,
            timeout=PRETTIER_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode == 0:
            return FormatResult(path, True, None)
        return FormatResult(
            path,
            False,
            result.stderr or result.stdout or "Unknown error",
        )
    except Exception as e:
        return FormatResult(path, False, str(e))


def process_file_wrapper(path: Path) -> FormatResult:
    """Format ``path`` and move it to ``error/`` on failure."""
    result: FormatResult = format_file(path)
    if not result.success:
        move_to_error_folder(result.path)
    return result


def main() -> None:
    """CLI entry point: format every matching file in the current directory."""
    cwd: Path = Path.cwd()
    files: list[Path] = get_files_to_format(cwd)

    if not files:
        logger.info("No files found to format.")
        return

    logger.info("{} files found", len(files))

    success_count: int = 0
    error_count: int = 0

    with Pool(processes=MAX_WORKERS) as pool:
        for result in pool.imap_unordered(process_file_wrapper, files):
            if result.success:
                logger.info("✅ Formatted: {}", result.path.name)
                success_count += 1
            else:
                logger.error(
                    "❌ Error: {} | Reason: {}", result.path.name, result.error_msg
                )
                error_count += 1

    logger.info("Summary: {} success, {} errors.", success_count, error_count)


if __name__ == "__main__":
    raise SystemExit(main())
