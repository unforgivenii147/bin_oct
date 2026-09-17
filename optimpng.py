#!/data/data/com.termux/files/home/.local/bin/python
"""
Optimize all PNG files under the current directory using optipng with a
multiprocessing pool of 8 workers, log progress with loguru, and report
the number of successfully optimized files.
"""

from __future__ import annotations

import subprocess
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger
from tqdm import tqdm

MAX_WORKERS: Final[int] = 8
PNG_SUFFIX: Final[str] = ".png"


def find_png_files(directory: Path) -> list[Path]:
    """
    Recursively find all PNG files under ``directory``.

    Args:
        directory: Root directory to search.

    Returns:
        A list of paths to PNG files.
    """
    return [p for p in directory.rglob("*") if p.suffix.lower() == PNG_SUFFIX]


def optimize_png(path: Path) -> tuple[bool, Path, str | None]:
    """
    Optimize a single PNG file using ``optipng -o7``.

    Args:
        path: Path to the PNG file to optimize.

    Returns:
        A tuple ``(success, path, error_message)`` where ``error_message``
        is ``None`` on success.
    """
    try:
        subprocess.run(
            ["optipng", "-o7", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return False, path, str(exc)
    else:
        return True, path, None


def main() -> int:
    """
    Entry point: find PNGs in the current directory and optimize them in parallel.

    Returns:
        Process exit code (0 on success).
    """
    cwd: Path = Path.cwd()
    png_files: list[Path] = find_png_files(cwd)
    if not png_files:
        logger.warning("No PNG files found in the current directory.")
        return 0

    print(f"Found {len(png_files)} PNG files to optimize.")

    results: list[tuple[bool, Path, str | None]] = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(optimize_png, (file,)) for file in png_files]
        with tqdm(total=len(png_files), desc="Optimizing PNGs", unit="file") as pbar:
            for async_result in async_results:
                results.append(async_result.get())
                pbar.update(1)

    success: int = sum(1 for ok, _, _ in results if ok)
    print(f"Optimization complete. Success: {success}/{len(png_files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
