#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import logging
import multiprocessing
import os
import time
from collections.abc import Generator
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
MAX_CHUNK_LEN: Final[int] = 5000
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def is_text_file(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(512)
            if not chunk:
                return False
            return b"\x00" not in chunk
    except OSError:
        return False


def get_chunks(text: str, max_len: int = MAX_CHUNK_LEN) -> Generator[str, None, None]:
    lines = text.splitlines(keepends=True)
    current_chunk: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line)
        if current_len + line_len > max_len and current_chunk:
            yield "".join(current_chunk)
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len
    if current_chunk:
        yield "".join(current_chunk)


def translate_file_task(task: tuple[Path, str, float, Path | None]) -> None:
    path, target_lang, delay, output_dir = task
    print("[%d] Processing: %s", os.getpid(), path)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error("  ✗ Cannot read: %s (%s)", path, e)
        return
    if not content.strip():
        print("  ⊘ Empty file, skipping: %s", path)
        return
    translator = GoogleTranslator(source="auto", target=target_lang)
    translated_chunks: list[str] = []
    chunks = list(get_chunks(content))
    for i, chunk in enumerate(chunks, 1):
        try:
            translated = translator.translate(chunk)
            if translated:
                preview = translated[:80].replace("\n", " ")
                print("    [%d/%d] %s...", i, len(chunks), preview)
                translated_chunks.append(translated)
            else:
                translated_chunks.append(chunk)
        except Exception as e:
            logger.error("  ✗ Translation error in chunk %d/%d: %s", i, len(chunks), e)
            return
        if i < len(chunks):
            time.sleep(delay)
    translated_text = "".join(translated_chunks)
    if path.suffix.lower() == ".py":
        try:
            ast.parse(translated_text)
            print("  ✓ Python syntax valid")
        except SyntaxError as e:
            logger.error("  ✗ Syntax error in translated Python, NOT writing: %s", e)
            return
    if output_dir:
        try:
            rel_path = path.relative_to(Path.cwd())
        except ValueError:
            rel_path = path.name
        out_path = (output_dir / rel_path).with_suffix(f"{path.suffix}.{target_lang}")
    else:
        out_path = path.with_suffix(f"{path.suffix}.{target_lang}")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(translated_text, encoding="utf-8")
        print("  → Written: %s\n", out_path)
    except Exception as e:
        logger.error("  ✗ Cannot write output: %s (%s)\n", out_path, e)


def collect_files(paths: list[str]) -> list[Path]:
    files: set[Path] = set()
    for p in paths:
        path = Path(p).resolve()
        if path.is_file():
            if is_text_file(path):
                files.add(path)
        elif path.is_dir():
            for entry in path.rglob("*"):
                if (
                    entry.is_file()
                    and (not any(part in SKIP_DIRS for part in entry.parts))
                    and is_text_file(entry)
                ):
                    files.add(entry)
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recursive text file translator.")
    parser.add_argument(
        "paths", nargs="*", default=["."], help="Files/directories to process"
    )
    parser.add_argument(
        "--target-lang", default="en", help="Target language (default: en)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="Delay between chunks (default: 0.5)"
    )
    parser.add_argument(
        "--workers", type=int, help="Parallel workers (default: CPU count)"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Target directory for translations"
    )
    args = parser.parse_args()
    workers = args.workers or multiprocessing.cpu_count()
    files = collect_files(args.paths)
    if not files:
        print("No text files found to process.")
        return
    print("Found %d text files. Starting %d workers...\n", len(files), workers)
    tasks = [(f, args.target_lang, args.delay, args.output_dir) for f in files]
    with multiprocessing.Pool(processes=workers) as pool:
        pool.map(translate_file_task, tasks)
    print("\n✓ All files processed.")


if __name__ == "__main__":
    raise SystemExit(main())
