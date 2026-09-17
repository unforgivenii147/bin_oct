#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that translates non-English text files (.md, .txt) in a directory
tree to English using deep_translator's GoogleTranslator, processing files concurrently with
multiprocessing.Pool.apply_async using a fixed pool of 8 workers, logging via loguru, handling
paths with pathlib, and safely overwriting files using a temporary file + atomic move.
"""

import re
import shutil
import sys
import tempfile
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from loguru import logger

NON_ENGLISH_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")
MAX_WORKERS: Final[int] = 8
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
    }
)


def is_english(text: str) -> bool:
    """Return True if the given text contains only ASCII characters."""
    return not NON_ENGLISH_PATTERN.search(text)


def get_files(
    path: Path, include_hidden: bool = True, extensions: tuple[str, ...] | None = None
) -> list[Path]:
    """Recursively collect files under ``path`` matching optional extension filter."""
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    files: list[Path] = []
    stack: list[Path] = [path]
    while stack:
        current: Path = stack.pop()
        try:
            for entry in current.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file():
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    if extensions is None or entry.suffix.lower() in extensions:
                        files.append(entry)
        except PermissionError:
            logger.warning("Permission denied: {}", current)
            continue
    return sorted(files)


def translate_text(text: str) -> str:
    """Translate non-English lines of ``text`` to English, preserving line endings."""
    if not text:
        return text
    lines: list[str] = text.splitlines(keepends=True)
    translated_lines: list[str] = []
    translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
    for line in lines:
        stripped_line: str = line.strip()
        if not stripped_line or is_english(stripped_line):
            translated_lines.append(line)
        else:
            try:
                result: str | None = translator.translate(stripped_line)
                ending: str = "\n" if line.endswith("\n") else ""
                translated_lines.append(f"{result}{ending}" if result else line)
            except Exception as e:
                logger.error("Translation error on line: {}", e)
                translated_lines.append(line)
    return "".join(translated_lines)


def safe_overwrite(path: Path, content: str) -> None:
    """Atomically overwrite ``path`` with ``content`` using a temp file."""
    tmp_path: Path
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        shutil.move(str(tmp_path), str(path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to overwrite {path}: {e}") from e


def process_file(path: Path) -> str:
    """Read, translate if needed, and atomically overwrite a single file."""
    try:
        original: str = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading {path}: {e}"
    if is_english(original.strip()):
        return f"Skipped (English): {path.name}"
    try:
        translated: str = translate_text(original)
        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            return f"✓ Updated: {path.name}"
        return f"No changes: {path.name}"
    except Exception as e:
        return f"Failed to process {path}: {e}"


def main() -> None:
    """Entry point: gather target files and dispatch translation jobs to a Pool."""
    args: list[str] = sys.argv[1:]
    cwd: Path = Path.cwd()
    files: list[Path]
    if args:
        files = [Path(p) for p in args if Path(p).is_file()]
    else:
        files = get_files(cwd, extensions=(".md", ".txt"))
    if not files:
        print("No files found to process.")
        return
    print("Starting processing of {} files...", len(files))
    pool: Pool = Pool(processes=MAX_WORKERS)
    try:
        results: list[AsyncResult[str]] = [
            pool.apply_async(process_file, (f,)) for f in files
        ]
        pool.close()
        for result in results:
            try:
                print(result.get())
            except Exception as e:
                logger.error("Worker error: {}", e)
        pool.join()
    finally:
        pool.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
