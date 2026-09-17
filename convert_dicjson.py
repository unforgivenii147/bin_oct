#!/data/data/com.termux/files/home/.local/bin/python
import json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path


def process_file(json_file):
    """Extract word -> list of Persian meanings from a single JSON file."""
    try:
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to read {json_file}: {e}")
        return []

    results = []
    words = data.get("Words", []) if isinstance(data, dict) else []
    for entry in words:
        english = entry.get("EnglishWord")
        meanings = entry.get("Meanings", [])
        if not english or not meanings:
            continue
        # The first item is the Persian translation; the rest is context/explanation.
        persian = meanings[0]
        results.append((english, persian))
    return results


def main():
    cwd = Path.cwd()
    json_files = [
        p for p in cwd.glob("*.json") if p.name != f"{cwd.name}.json"
    ]  # avoid picking up our own output

    if not json_files:
        print("No JSON files found in the current directory.")
        return

    merged = defaultdict(list)

    # Use a fixed pool of 8 workers with apply_async
    pool = mp.Pool(processes=8)
    try:
        async_results = [pool.apply_async(process_file, args=(f,)) for f in json_files]
        for ar in async_results:
            for english, persian in ar.get():
                # Avoid duplicate translations for the same word
                if persian not in merged[english]:
                    merged[english].append(persian)
    finally:
        pool.close()
        pool.join()

    # Sort keys for stable output (optional)
    merged_sorted = {k: merged[k] for k in sorted(merged.keys())}

    output_file = cwd / f"{cwd.name}.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(merged_sorted, f, ensure_ascii=False, indent=2)

    # Remove original files (but never the output file)
    for f in json_files:
        if f.resolve() != output_file.resolve():
            f.unlink()

    print(f"Wrote {len(merged_sorted)} entries to {output_file}")
    print(f"Removed {len(json_files)} original file(s).")


if __name__ == "__main__":
    main()
