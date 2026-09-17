#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import mmap
import sys
from collections import defaultdict
from pathlib import Path


def get_lines(path: Path) -> list[str]:
    file_size = path.stat().st_size
    if file_size > 5 * 1024 * 1024:
        print(
            f"[Info] Large file detected ({file_size / (1024 * 1024):.2f} MB). Using mmap..."
        )
        with (
            path.open("r+b") as f,
            mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
        ):
            content = mm.read().decode("utf-8", errors="ignore")
            return [line.strip() for line in content.splitlines() if line.strip()]
    else:
        print("[Info] Small file detected. Using standard read...")
        with path.open("r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]


def process_wordlist(path_str: str) -> None:
    path = Path(path_str)
    if not path.exists():
        print(f"Error: File '{path_str}' does not exist.")
        sys.exit(1)
    lines = get_lines(path)
    buckets = defaultdict(list)
    for word in lines:
        for i in range(len(word)):
            wildcard = word[:i] + "*" + word[i + 1 :]
            buckets[wildcard].append(word)
    similar_lines = set()
    for matched_words in buckets.values():
        if len(matched_words) > 1:
            for word in matched_words:
                similar_lines.add(word)
    if not similar_lines:
        print("No similar items found.")
        return
    remaining_lines = [line for line in lines if line not in similar_lines]
    similar_file = Path("similar.txt")
    with similar_file.open("a", encoding="utf-8") as sf:
        for line in sorted(similar_lines):
            sf.write(line + "\n")
    with path.open("w", encoding="utf-8") as f:
        for line in remaining_lines:
            f.write(line + "\n")
    print(f"[Success] Moved {len(similar_lines)} lines to {similar_file}")
    print(
        f"[Success] Updated {path_str} in-place ({len(remaining_lines)} lines remaining)."
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python filter_passwords.py <filename>")
        sys.exit(1)
    target_file = sys.argv[1]
    process_wordlist(target_file)
