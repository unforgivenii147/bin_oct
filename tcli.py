#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate every line of an input file (English dictionary, one word per line)
to Persian using the `translate` library, with a multiprocessing pool.

Usage:
    python translate_words.py <input_file> [output_file]
"""

import json
import multiprocessing as mp
import sys
from pathlib import Path

from translate import Translator

# Fixed number of workers
N_WORKERS = 8
# Source / target languages
SOURCE_LANG = "en"
TARGET_LANG = "fa"


def translate_word(word: str) -> dict:
    """
    Translate a single word. Runs inside a worker process, so each worker
    builds its own Translator instance.
    """
    word = word.strip()
    if not word:
        return {"source": word, "translation": None, "error": "empty"}

    try:
        translator = Translator(from_lang=SOURCE_LANG, to_lang=TARGET_LANG)
        translation = translator.translate(word)
        print(f"{word} -> {translation}")
        return {"source": word, "translation": translation, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"source": word, "translation": None, "error": str(exc)}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file> [output_file]", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])
    if not input_path.is_file():
        print(f"Error: input file '{input_path}' not found.", file=sys.stderr)
        return 1

    # Default output: <input_stem>.fa.json next to the input file
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_suffix(".fa.json")

    # Read words (one per line)
    words = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(words)} words from {input_path}", file=sys.stderr)

    # Translate in parallel with 8 workers
    with mp.Pool(processes=N_WORKERS) as pool:
        results = pool.map(translate_word, words)

    # Save results as JSON
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} entries to {output_path}", file=sys.stderr)

    # Quick summary of failures (if any)
    failures = sum(1 for r in results if r["error"])
    if failures:
        print(f"Warning: {failures} entries failed.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
