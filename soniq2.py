#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python script that sorts and de-duplicates the lines of a text file.

The script reads a file, strips whitespace from each line, removes duplicates,
sorts the unique lines, and atomically writes the result back to the same path.
For files larger than 5 MB it memory-maps the file for reading. Line stripping
is parallelized with a fixed multiprocessing pool of 8 workers. It uses
`pathlib` for all path handling, `loguru` for logging, and supports a single
positional CLI argument: the file path. Temporary output is written to a
`tempfile.NamedTemporaryFile`-style sibling file and then atomically replaced.
"""

from __future__ import annotations

import mmap
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger

MB_5: Final[int] = 5 * 1024 * 1024
POOL_SIZE: Final[int] = 8


def _strip_line(line: str) -> str:
    """Return the given line with leading and trailing whitespace removed."""
    return line.strip()


def sort_and_uniq(path: str) -> None:
    """Sort and de-duplicate lines in ``path`` in place.

    Args:
        path: Path to the file to process.
    """
    path = Path(path)
    if not path.exists():
        logger.error("File '{}' not found.", path)
        return

    try:
        size: int = path.stat().st_size

        if size > MB_5:
            with (
                path.open("r+b") as f,
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            ):
                lines: list[str] = mm.read().decode("utf-8").splitlines()
        else:
            lines = path.read_text(encoding="utf-8").splitlines()

        with Pool(processes=POOL_SIZE) as pool:
            async_results = [pool.apply_async(_strip_line, (line,)) for line in lines]
            processed_lines: list[str] = [res.get() for res in async_results]

        unique_sorted_lines: list[str] = sorted(set(processed_lines))

        fd, temp_path_str = tempfile.mkstemp(dir=path.parent)
        temp_path = Path(temp_path_str)
        try:
            with open(fd, "w", encoding="utf-8") as tmp:
                tmp.writelines(line + "\n" for line in unique_sorted_lines)
            temp_path.replace(path)
            print("Successfully updated '{}'.", path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    except Exception as e:
        logger.error("Failed to process file: {}", e)


def main() -> None:
    """Entry point: parse CLI args and run :func:`sort_and_uniq`."""
    if len(sys.argv) < 2:
        print("Usage: python script.py <filename>")
        return
    sort_and_uniq(sys.argv[1])


if __name__ == "__main__":
    main()
