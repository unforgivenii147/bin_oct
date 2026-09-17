#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate non-English text files in place using deep-translator's GoogleTranslator.
Discovers targets from CLI args (or via ``dh.get_nobinary`` on the CWD), skips
files whose content is already ASCII/English, writes changes atomically via a
temp file + move, and retries failed files up to ``MAX_RETRIES`` times with a
``RETRY_DELAY`` pause. Uses a fixed multiprocessing.Pool of 8 workers; logging
via loguru.
"""

import re
import shutil
import sys
import tempfile
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from dh import get_nobinary  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
MAX_RETRIES: Final[int] = 2
RETRY_DELAY: Final[float] = 3.0
NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")


def is_english(text: str) -> bool:
    """
    Decide whether ``text`` looks like pure ASCII/English content.

    Args:
        text: The text to inspect.

    Returns:
        ``True`` if no non-ASCII characters are present, otherwise ``False``.
    """
    return not NON_ENGLISH_PATTERN.search(text)


def safe_overwrite(filepath: Path, content: str) -> None:
    """
    Atomically overwrite ``filepath`` with ``content``.

    Writes to a temporary file in the same directory, then moves it over the
    destination so partial writes cannot corrupt the target.

    Args:
        filepath: Destination path.
        content: New file content (UTF-8).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(filepath.parent)
    ) as tmp:
        tmp.write(content)
        tmp_path: Path = Path(tmp.name)
    shutil.move(str(tmp_path), str(filepath))


def translate_file_content(path: Path, retries: int = MAX_RETRIES) -> str:
    """
    Translate the contents of a file into English.

    Retries up to ``retries`` times on translator failure, sleeping
    :data:`RETRY_DELAY` seconds between attempts. If all attempts fail, the
    original file content is returned unchanged.

    Args:
        path: Source file to translate.
        retries: Number of translation attempts before giving up.

    Returns:
        The translated text, or the original text if translation failed.
    """
    for attempt in range(retries):
        try:
            translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
            result: str | None = translator.translate_file(str(path))
            return (
                result
                if result is not None
                else path.read_text(encoding="utf-8", errors="ignore")
            )
        except Exception as exc:
            if attempt < (retries - 1):
                logger.warning(
                    f"File translation attempt {attempt + 1} failed for {path}: {exc}. "
                    f"Retrying in {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
            else:
                logger.error(
                    f"File translation failed after {retries} attempts for {path}: {exc}"
                )
                return path.read_text(encoding="utf-8", errors="ignore")

    return path.read_text(encoding="utf-8", errors="ignore")


def process_file(path: Path) -> Path | None:
    """
    Translate a single file in place if it contains non-English content.

    Args:
        path: File to process.

    Returns:
        ``path`` if processing failed (so the caller can retry), otherwise
        ``None`` on success or when the file was already English.
    """
    print(f"  Processing {path.name}...")
    try:
        original: str = path.read_text(encoding="utf-8", errors="ignore")
        if is_english(original):
            return None

        translated: str = translate_file_content(path)
        logger.debug(translated)

        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            print(f"  ✓ Updated {path.name}")
        return None
    except Exception as exc:
        logger.error(f"  Failed to process {path}: {exc}")
        return path


def process_files_with_retry(files: list[Path]) -> None:
    """
    Process files in parallel with retries for failures.

    Uses a fixed :class:`multiprocessing.Pool` of :data:`MAX_WORKERS` workers
    and re-submits failed files up to :data:`MAX_RETRIES` times.

    Args:
        files: Initial list of file paths to process.
    """
    files_to_process: list[Path] = list(files)
    retry_count: int = 0

    while files_to_process and retry_count < MAX_RETRIES:
        if retry_count > 0:
            print("=" * 40)
            print(f"Retry attempt {retry_count}/{MAX_RETRIES}")
            print(f"Retrying {len(files_to_process)} failed files...")
            print("=" * 40)
            time.sleep(RETRY_DELAY)

        failed_files: list[Path] = []

        with Pool(processes=MAX_WORKERS) as pool:
            async_results: list[AsyncResult[Path | None]] = [
                pool.apply_async(process_file, (f,)) for f in files_to_process
            ]
            for f, async_res in zip(files_to_process, async_results):
                try:
                    failed: Path | None = async_res.get()
                    if failed is not None:
                        failed_files.append(failed)
                except Exception as exc:
                    logger.error(f"File {f} generated an exception: {exc}")
                    failed_files.append(f)

        files_to_process = failed_files
        retry_count += 1
        if failed_files:
            logger.warning(f"{len(failed_files)} files failed and will be retried.")

    if files_to_process:
        logger.error(
            f"Failed to process {len(files_to_process)} files after "
            f"{MAX_RETRIES} retries:"
        )
        for f in files_to_process:
            logger.error(f"  - {f}")


def main() -> None:
    """Entry point: collect target files and translate them in parallel."""
    args: list[str] = sys.argv[1:]
    files: list[Path] = (
        [Path(p) for p in args] if args else list(get_nobinary(Path.cwd()))
    )

    if not files:
        print("No files found to process.")
        return

    print(f"Found {len(files)} files to process.")
    process_files_with_retry(files)


if __name__ == "__main__":
    raise SystemExit(main())
