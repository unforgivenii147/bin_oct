#!/data/data/com.termux/files/home/.local/bin/python
"""Pack all wheel directories in a folder in parallel using a fixed pool of 8 processes.

This script scans a target directory for subdirectories, runs `wheel pack` on each
one concurrently via multiprocessing.Pool.apply_async with a fixed pool of 8
workers, and logs per-directory success or failure messages with loguru.
"""

from __future__ import annotations

import argparse
import subprocess
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

# Fixed number of parallel workers for the multiprocessing pool.
POOL_SIZE: int = 8


def pack_wheel(directory: Path) -> tuple[bool, str]:
    """Run `wheel pack` on a single directory.

    Args:
        directory: Path to the directory to pack.

    Returns:
        A tuple of (success, message) where success indicates whether the
        command completed successfully and message is a human-readable status.
    """
    try:
        subprocess.run(
            ["wheel", "pack", str(directory)],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"✓ {directory.name}"
    except subprocess.CalledProcessError as e:
        return False, f"✗ {directory.name}: {e.stderr.strip()}"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        The parsed argparse namespace containing `directory`.
    """
    parser = argparse.ArgumentParser(description="Pack wheel directories in parallel")
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory containing wheel dirs (default: current)",
    )
    return parser.parse_args()


def main() -> int:
    """Entry point: pack every subdirectory of the target directory in parallel.

    Returns:
        Exit code: 0 on full success, 1 if any directory failed or none found.
    """
    args: argparse.Namespace = parse_args()
    directories: list[Path] = [d for d in args.directory.iterdir() if d.is_dir()]
    if not directories:
        logger.warning("No directories found")
        return 1

    print(
        "Processing {} directories using {} workers",
        len(directories),
        POOL_SIZE,
    )

    success_count: int = 0
    fail_count: int = 0

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            (directory, pool.apply_async(pack_wheel, (directory,)))
            for directory in directories
        ]
        for directory, async_result in async_results:
            try:
                success, message = async_result.get()
                print(message)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:  # noqa: BLE001
                logger.error("✗ {}: Exception - {}", directory.name, e)
                fail_count += 1

    print("Done: {} successful, {} failed", success_count, fail_count)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
