#!/data/data/com.termux/files/home/.local/bin/python
"""Word frequency counter: scan text files in a directory, count lowercase words in parallel using multiprocessing.Pool with 8 workers, and save sorted results to counter.json with loguru logging."""

import json
import re
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from dh import get_nobinary
from loguru import logger

MAX_WORKERS: int = 8
WORD_PATTERN: re.Pattern[str] = re.compile(r"\b[a-z]+\b")
OUTPUT_FILE: Path = Path("counter.json")


def process_file(path: Path) -> Counter[str]:
    """Count lowercase word occurrences in a single file.

    Args:
        path: Path to the file to process.

    Returns:
        A Counter mapping words to their frequencies in the file.
    """
    word_counter: Counter[str] = Counter()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content: str = f.read()
        words: list[str] = WORD_PATTERN.findall(content.lower())
        word_counter.update(words)
        logger.debug(f"Processed {path.name}: {len(words)} words found")
    except Exception as e:
        logger.warning(f"Failed to process {path}: {e}")
    return word_counter


def collect_text_files(directory: Path | None = None) -> list[Path]:
    """Collect candidate text files from a directory.

    Args:
        directory: Directory to scan. Defaults to the current working directory.

    Returns:
        A list of paths to text files.
    """
    if directory is None:
        directory = Path.cwd()
    text_files: list[Path] = get_nobinary(directory)
    print(f"Found {len(text_files)} text files to process")
    return text_files


def process_files_parallel(paths: list[Path]) -> Counter[str]:
    """Process files in parallel using a fixed-size multiprocessing pool.

    Args:
        paths: List of file paths to process.

    Returns:
        An aggregated Counter of word frequencies across all files.
    """
    total_counter: Counter[str] = Counter()
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_file, (path,)) for path in paths
        ]
        for path, async_result in zip(paths, async_results):
            try:
                file_counter: Counter[str] = async_result.get()
                total_counter.update(file_counter)
                logger.debug(f"Completed processing {path.name}")
            except Exception as e:
                logger.error(f"Error processing {path}: {e}")
    return total_counter


def _now_isoformat() -> str:
    """Return the current local time in ISO 8601 format.

    Returns:
        Current timestamp as an ISO 8601 string.
    """
    from datetime import datetime

    return datetime.now().isoformat()


def save_results_json(counter: Counter[str], output_file: Path) -> None:
    """Persist word counts and metadata to a JSON file.

    Args:
        counter: Aggregated word frequency counter.
        output_file: Destination path for the JSON output.
    """
    sorted_words: dict[str, int] = dict(
        sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    )
    results: dict[str, Any] = {
        "metadata": {
            "total_words": sum(counter.values()),
            "unique_words": len(counter),
            "timestamp": _now_isoformat(),
        },
        "word_counts": sorted_words,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {output_file}")


def main() -> int:
    """Run the word frequency analysis pipeline.

    Returns:
        Process exit code (0 on success).
    """
    directory: Path = Path.cwd()
    print(f"Starting word frequency analysis in {directory}")

    text_files: list[Path] = collect_text_files(directory)
    if not text_files:
        logger.warning("No text files found in the current directory!")
        save_results_json(Counter(), OUTPUT_FILE)
        return 0

    print(f"Processing {len(text_files)} files using parallel processing...")
    total_counter: Counter[str] = process_files_parallel(text_files)

    unique_words: int = len(total_counter)
    total_words: int = sum(total_counter.values())

    save_results_json(total_counter, OUTPUT_FILE)

    print("Analysis complete!")
    print(f"Total words found: {total_words}")
    print(f"Unique words found: {unique_words}")

    print("=" * 40)
    print("Top 10 Most Common Words:")
    print("-" * 40)
    for word, count in total_counter.most_common(10):
        print(f"{word:<20} {count:>8}")
    print("-" * 40)
    print(f"Full results saved to: {OUTPUT_FILE.absolute()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
