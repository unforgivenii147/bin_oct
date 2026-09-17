#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that walks the current working directory and
translates non-English lines in matching text/code files to English.

The generated script should:
- Recursively scan the current directory for files matching the patterns
  "*.txt", "*.md", "*.py", "*.json", "*.csv", skipping directories named
  "lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache",
  ".pytest_cache", and any path component starting with a dot.
- Detect lines containing non-Latin scripts (Arabic, CJK, Hiragana, Katakana,
  Hangul, Cyrillic) using a compiled regex.
- Translate each matching line via deep_translator.GoogleTranslator
  (source="auto", target="en"), preserving leading whitespace and the
  trailing newline, and only rewriting files that changed.
- Process files concurrently with multiprocessing.Pool.imap_unordered using
  a fixed pool of 8 workers (no CLI flag controls parallelism).
- Log all progress and results with loguru.
- Include complete type annotations, docstrings on every function, and this
  module-level docstring.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Final, List, Optional

from deep_translator import GoogleTranslator
from loguru import logger

POOL_SIZE: Final[int] = 8
FILE_PATTERNS: Final[tuple[str, ...]] = ("*.txt", "*.md", "*.py", "*.json", "*.csv")

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

LANGUAGE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF\u0400-\u04FF]"
)


def is_foreign_line(line: str) -> bool:
    """Return True if ``line`` contains non-Latin script characters.

    Args:
        line: The line of text to inspect.

    Returns:
        ``True`` if any character matches the non-Latin script ranges.
    """
    return bool(LANGUAGE_PATTERN.search(line))


def _should_skip(path: Path) -> bool:
    """Return True if ``path`` should be excluded from processing.

    Args:
        path: Candidate file or directory path.

    Returns:
        ``True`` when any path component is hidden or is in ``SKIP_DIRS``.
    """
    part: str
    for part in path.parts:
        if part.startswith(".") or part in SKIP_DIRS:
            return True
    return False


def process_file(file_path: Path) -> str:
    """Translate non-English lines in ``file_path`` in place.

    Args:
        file_path: Path of the file to process.

    Returns:
        A human-readable status message describing the outcome.
    """
    try:
        content: str = file_path.read_text(encoding="utf-8")
        lines: list[str] = content.splitlines(keepends=True)
        translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
        modified: bool = False
        new_lines: list[str] = []

        line: str
        for line in lines:
            stripped: str = line.strip()
            if stripped and is_foreign_line(stripped):
                try:
                    translated_raw: object = translator.translate(stripped)
                    translated: str | None = (
                        translated_raw if isinstance(translated_raw, str) else None
                    )
                    if translated:
                        indent: str = line[: len(line) - len(line.lstrip())]
                        ending: str = "\n" if line.endswith("\n") else ""
                        new_lines.append(f"{indent}{translated}{ending}")
                        modified = True
                    else:
                        new_lines.append(line)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error translating line in {}: {}", file_path, exc)
                    new_lines.append(line)
            else:
                new_lines.append(line)

        if modified:
            file_path.write_text("".join(new_lines), encoding="utf-8")
            return f"✓ Updated: {file_path}"
        return f"No changes: {file_path}"
    except Exception as exc:  # noqa: BLE001
        return f"Error processing {file_path}: {exc}"


def _collect_files(root: Path) -> list[Path]:
    """Collect candidate files under ``root`` matching ``FILE_PATTERNS``.

    Args:
        root: Directory to scan recursively.

    Returns:
        A list of file paths that are not inside skipped or hidden directories.
    """
    files: list[Path] = []
    pattern: str
    for pattern in FILE_PATTERNS:
        path: Path
        for path in root.rglob(pattern):
            if _should_skip(path):
                continue
            if path.is_file():
                files.append(path)
    return files


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the translation script.

    Args:
        argv: Optional argument vector (currently unused; reserved for
            future options).

    Returns:
        Process exit code (0 on success).
    """
    _ = list(argv) if argv is not None else sys.argv[1:]

    cwd: Path = Path(".")
    files_to_process: list[Path] = _collect_files(cwd)

    if not files_to_process:
        logger.info("No files found to process.")
        return 0

    logger.info("Starting processing of {} files...", len(files_to_process))

    with Pool(processes=POOL_SIZE) as pool:
        message: str
        for message in pool.imap_unordered(process_file, files_to_process):
            logger.info("{}", message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
