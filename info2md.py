#!/data/data/com.termux/files/home/.local/bin/python
"""Convert `.info` files to Markdown using the `info` command.

Prompt: Write a Python script that, for every `*.info*` file in the current
working directory, runs the external `info` command to render it to Markdown,
writes the output to a sibling `.md` file (avoiding collisions by appending
`_N`), and deletes the original `.info` file on success. Use `multiprocessing.
Pool.apply_async` with a fixed pool of 8 workers, `pathlib` for all path
handling, `loguru` for logging, and full type annotations.
"""

from __future__ import annotations

import re
import sys
from multiprocessing import Pool
from pathlib import Path
from subprocess import run

from loguru import logger

WORKERS: int = 8
INFO_SUFFIX_PATTERN: re.Pattern[str] = re.compile(r"\.info(-\d+)?$")


def convert_info_file(info_path: Path) -> None:
    """Render a single `.info` file to Markdown and remove the original.

    Args:
        info_path: Path to the `.info` file to convert.
    """
    stem: str = info_path.name
    base_name: str = INFO_SUFFIX_PATTERN.sub("", stem)
    md_path: Path = info_path.parent / f"{base_name}.md"

    if md_path.exists():
        index: int = 1
        while (info_path.parent / f"{base_name}_{index}.md").exists():
            index += 1
        md_path = info_path.parent / f"{base_name}_{index}.md"

    result = run(
        ["info", str(info_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        md_path.write_text(result.stdout)
        info_path.unlink()
        print(f"Converted {info_path.name} -> {md_path.name}")
    else:
        logger.error(
            f"Failed to convert {info_path.name} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )


def main() -> int:
    """Entry point: convert all `.info` files in the CWD using a process pool.

    Returns:
        Process exit code (0 on success).
    """
    cwd: Path = Path.cwd()
    info_files: list[Path] = list(cwd.glob("*.info*"))

    if not info_files:
        print("No .info files found.")
        return 0

    print(f"Converting {len(info_files)} .info file(s) with {WORKERS} workers.")

    with Pool(processes=WORKERS) as pool:
        async_results = [
            pool.apply_async(convert_info_file, (info_path,))
            for info_path in info_files
        ]
        for async_result in async_results:
            try:
                async_result.get()
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"Worker raised an exception: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
