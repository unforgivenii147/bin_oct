#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that comments out a range of lines in a source file.

The generated script should:
- Accept `<filename> <start_line> [end_line]` as positional CLI arguments.
- Choose the comment prefix based on the file extension using a COMMENT_MAP,
  defaulting to `#` and warning for unknown extensions.
- Stream the input file in chunks of 10,000 lines, comment out only lines
  between start_line and end_line (inclusive, 1-based), and write output to a
  temporary file that atomically replaces the original.
- Preserve blank lines and lines that already begin with the comment prefix.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers (no
  CLI flag controls parallelism).
- Use loguru for all logging and pathlib for all filesystem operations.
- Include complete type hints, docstrings on every function, and this
  module-level docstring.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Optional

from loguru import logger

POOL_SIZE: int = 8
CHUNK_SIZE: int = 10_000
DEFAULT_COMMENT: str = "#"

COMMENT_MAP: dict[str, str] = {
    ".vim": '"',
    ".lua": "--",
    ".py": "#",
    ".sh": "#",
    ".toml": "#",
    ".yml": "#",
    ".yaml": "#",
    ".js": "//",
    ".ts": "//",
    ".cpp": "//",
    ".c": "//",
    ".cs": "//",
    ".java": "//",
    ".sql": "--",
    ".rb": "#",
}


def process_chunk(lines: Sequence[str], comment_char: str) -> list[str]:
    """Prefix non-blank, non-already-commented lines with ``comment_char``.

    Args:
        lines: Lines to process.
        comment_char: Comment prefix for the target language.

    Returns:
        A new list of lines with the requested prefix applied.
    """
    processed: list[str] = []
    line: str
    for line in lines:
        stripped: str = line.lstrip()
        if not stripped or stripped.startswith(comment_char):
            processed.append(line)
        else:
            processed.append(f"{comment_char}{line}")
    return processed


def _parse_args(argv: Sequence[str]) -> tuple[Path, int, int | None]:
    """Parse CLI arguments into (path, start_line, end_line).

    Args:
        argv: Full argument vector, including the program name at index 0.

    Returns:
        A tuple of the target path, the 1-based start line, and the optional
        1-based end line.

    Raises:
        SystemExit: If the arguments are invalid or the file does not exist.
    """
    if not 3 <= len(argv) <= 4:
        logger.error("Usage: python commentout.py <filename> <start_line> [end_line]")
        raise SystemExit(1)

    file_path: Path = Path(argv[1])
    if not file_path.exists():
        logger.error("File {} not found.", file_path)
        raise SystemExit(1)

    try:
        start_line: int = int(argv[2])
        end_line: int | None = int(argv[3]) if len(argv) == 4 else None
    except ValueError:
        logger.error("Line numbers must be integers.")
        raise SystemExit(1)

    return file_path, start_line, end_line


def _resolve_comment_char(file_path: Path) -> str:
    """Return the comment prefix appropriate for ``file_path``'s extension.

    Falls back to ``DEFAULT_COMMENT`` and logs a warning for unknown
    extensions.
    """
    ext: str = file_path.suffix.lower()
    comment_char: str | None = COMMENT_MAP.get(ext)
    if comment_char is None:
        logger.warning(
            "Unknown extension {}. Using default '{}' as comment char.",
            ext,
            DEFAULT_COMMENT,
        )
        return DEFAULT_COMMENT
    return comment_char


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point: comment out a line range within a source file.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        Process exit code (0 on success).
    """
    args: list[str] = list(argv) if argv is not None else sys.argv
    file_path: Path
    start_line: int
    end_line: int | None
    file_path, start_line, end_line = _parse_args(args)
    comment_char: str = _resolve_comment_char(file_path)

    target_end: int = end_line if end_line is not None else sys.maxsize

    temp_path: Path
    with (
        file_path.open("r", encoding="utf-8", errors="ignore") as infile,
        NamedTemporaryFile(
            "w", delete=False, dir=file_path.parent, encoding="utf-8"
        ) as temp_file,
    ):
        temp_path = Path(temp_file.name)
        current_line_idx: int = 1

        with Pool(processes=POOL_SIZE) as pool:
            while True:
                raw: list[str] = [infile.readline() for _ in range(CHUNK_SIZE)]
                lines: list[str] = [line for line in raw if line]
                if not lines:
                    break

                chunk_start: int = current_line_idx
                chunk_end: int = current_line_idx + len(lines) - 1

                if chunk_start <= target_end and chunk_end >= start_line:
                    prefix_count: int = max(0, start_line - chunk_start)
                    suffix_start: int = (
                        max(0, target_end - chunk_start + 1)
                        if end_line is not None
                        else len(lines)
                    )
                    prefix: list[str] = lines[:prefix_count]
                    target_block: list[str] = lines[prefix_count:suffix_start]
                    suffix: list[str] = lines[suffix_start:]

                    async_result = pool.apply_async(
                        process_chunk, (target_block, comment_char)
                    )
                    temp_file.writelines(prefix)
                    temp_file.writelines(async_result.get())
                    temp_file.writelines(suffix)
                else:
                    temp_file.writelines(lines)

                current_line_idx += len(lines)

    temp_path.replace(file_path)
    logger.info("Successfully processed {} using '{}'", file_path, comment_char)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
