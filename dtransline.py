#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import time
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)


def is_english(text: str, threshold: float = 0.6) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    alpha_chars = [c for c in stripped if c.isalpha()]
    if not alpha_chars:
        return True
    ascii_alpha_count = sum(1 for c in alpha_chars if ord(c) < 128)
    return ascii_alpha_count / len(alpha_chars) > threshold


def translate_text(
    text: str, translator: GoogleTranslator, max_retries: int = 3
) -> str:
    if not text.strip() or is_english(text):
        return text
    for attempt in range(max_retries):
        try:
            result = translator.translate(text)
            if result:
                return result
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                logger.error(
                    "  Translation failed after %d attempts: %s", max_retries, e
                )
    return text


def process_file(path: Path) -> None:
    print("Processing: %s", path)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines(keepends=True)
        translator = GoogleTranslator(source="auto", target="en")
        translated_count = 0
        new_lines: list[str] = []
        for line in lines:
            if line.strip() and (not is_english(line)):
                leading_ws = line[: len(line) - len(line.lstrip())]
                trailing_ws = line[len(line.rstrip()) :]
                translated = translate_text(line.strip(), translator)
                new_lines.append(f"{leading_ws}{translated}{trailing_ws}")
                translated_count += 1
                if translated_count % 10 == 0:
                    print("  Progress: %d lines translated", translated_count)
            else:
                new_lines.append(line)
        if translated_count == 0:
            print("  No non-English lines found, skipping.")
            return
        path.write_text("".join(new_lines), encoding="utf-8", errors="ignore")
        print("  ✓ Completed: %d lines translated", translated_count)
    except Exception as e:
        logger.error("  ✗ Error processing %s: %s", path, e)


def worker(path: Path) -> None:
    process_file(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate non-English lines in-place."
    )
    parser.add_argument("files", nargs="+", help="Files or directories to process")
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=[".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv"],
        help="Extensions to process",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=mp.cpu_count(),
        help=f"Number of workers (default: {mp.cpu_count()})",
    )
    parser.add_argument("--exclude", nargs="+", default=[], help="Paths to exclude")
    args = parser.parse_args()
    exclude_paths = {Path(p).resolve() for p in args.exclude}
    files_to_process: list[Path] = []
    for entry in args.files:
        path = Path(entry)
        if path.is_file():
            if path.resolve() not in exclude_paths:
                files_to_process.append(path)
        elif path.is_dir():
            for ext in args.extensions:
                for fp in path.rglob(f"*{ext}"):
                    if (
                        fp.is_file()
                        and fp.resolve() not in exclude_paths
                        and (not any(part.startswith(".") for part in fp.parts))
                    ):
                        files_to_process.append(fp)
    if not files_to_process:
        print("No files to process.")
        return
    print("Found %d files. Using %d workers...", len(files_to_process), args.workers)
    if args.workers == 1:
        for fp in files_to_process:
            worker(fp)
    else:
        with mp.Pool(processes=args.workers) as pool:
            pool.map(worker, files_to_process)
    print("\n✓ All translations completed!")


if __name__ == "__main__":
    raise SystemExit(main())
