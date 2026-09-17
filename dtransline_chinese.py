#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import re
import time
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHINESE_PATTERN: Final[re.Pattern] = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u20000-\u2a6df\u2a700-\u2b73f\u2b740-\u2b81f\u2b820-\u2ceaf\uf900-\ufaff]"
)


def is_chinese_text(text: str, threshold: float = 0.3) -> bool:
    clean_text = "".join(text.split())
    if not clean_text:
        return False
    chinese_chars = len(CHINESE_PATTERN.findall(clean_text))
    return chinese_chars / len(clean_text) >= threshold


def translate_line(
    text: str, translator: GoogleTranslator, max_retries: int = 3
) -> str:
    if not text.strip():
        return text
    for attempt in range(max_retries):
        try:
            result = translator.translate(text)
            if result:
                time.sleep(0.05)
                return result
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 1.5
                logger.warning(
                    "  Retry %d/%d after %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    wait_time,
                    e,
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "  Translation failed after %d attempts: %s", max_retries, e
                )
    return text


def process_file(path: Path, dry_run: bool = False, threshold: float = 0.3) -> dict:
    stats = {
        "file": str(path),
        "total_lines": 0,
        "chinese_lines": 0,
        "translated_lines": 0,
        "errors": 0,
    }
    prefix = "[DRY RUN] " if dry_run else ""
    print("%sProcessing: %s", prefix, path)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines(keepends=True)
        stats["total_lines"] = len(lines)
        translator = GoogleTranslator(source="auto", target="en")
        new_lines: list[str] = []
        found_chinese = False
        for line in lines:
            if is_chinese_text(line, threshold):
                stats["chinese_lines"] += 1
                found_chinese = True
                if dry_run:
                    new_lines.append(line)
                else:
                    leading_ws = line[: len(line) - len(line.lstrip())]
                    trailing_ws = line[len(line.rstrip()) :]
                    translated = translate_line(line.strip(), translator)
                    new_lines.append(f"{leading_ws}{translated}{trailing_ws}")
                    stats["translated_lines"] += 1
                    if stats["translated_lines"] % 10 == 0:
                        print(
                            "  Progress: %d Chinese lines translated",
                            stats["translated_lines"],
                        )
            else:
                new_lines.append(line)
        if not dry_run and found_chinese:
            path.write_text("".join(new_lines), encoding="utf-8")
            print("  ✓ Completed: %d lines translated", stats["translated_lines"])
        elif dry_run and found_chinese:
            print("  ℹ Found %d lines with Chinese text", stats["chinese_lines"])
        elif not found_chinese:
            print("  No Chinese text found, skipping.")
    except Exception as e:
        logger.error("  ✗ Error processing %s: %s", path, e)
        stats["errors"] += 1
    return stats


def worker(args: tuple[Path, bool, float]) -> dict:
    return process_file(*args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate Chinese lines in-place.")
    parser.add_argument("files", nargs="+", help="Files or directories to process")
    parser.add_argument(
        "--extensions",
        "-e",
        nargs="+",
        default=[".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml", ".csv"],
        help="Extensions to process",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=mp.cpu_count(),
        help=f"Number of workers (default: {mp.cpu_count()})",
    )
    parser.add_argument(
        "--exclude", "-x", nargs="+", default=[], help="Paths to exclude"
    )
    parser.add_argument("--dry-run", "-d", action="store_true", help="Detection only")
    parser.add_argument(
        "--threshold", "-t", type=float, default=0.3, help="Chinese character threshold"
    )
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
    print(
        "Found %d files. Using %d workers (Threshold: %.0f%%)",
        len(files_to_process),
        args.workers,
        args.threshold * 40,
    )
    tasks = [(fp, args.dry_run, args.threshold) for fp in files_to_process]
    if args.workers == 1:
        all_stats = [worker(t) for t in tasks]
    else:
        with mp.Pool(processes=args.workers) as pool:
            all_stats = pool.map(worker, tasks)
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Files processed:   {len(all_stats)}")
    print(f"Chinese lines:     {sum(s['chinese_lines'] for s in all_stats):,}")
    if not args.dry_run:
        print(f"Translated lines:  {sum(s['translated_lines'] for s in all_stats):,}")
    print(f"Errors:            {sum(s['errors'] for s in all_stats)}")
    print("-" * 40)


if __name__ == "__main__":
    raise SystemExit(main())
