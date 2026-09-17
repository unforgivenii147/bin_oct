#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from collections import Counter, deque
from multiprocessing import Pool
from pathlib import Path

from dh import get_nobinary

MAX_WORKERS = 8


def extract_words(text: str) -> list[str]:
    splt = text.strip().lower().replace("/", " ")
    return re.findall("[a-z]{3,}", splt)


def process_file(path: Path) -> None:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    words = extract_words(text)
    filtered = list(words)
    for word, _count in Counter(filtered).most_common(30):
        print(f"{word}", end=" ")
    print()


def main() -> None:
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = [Path(arg) for arg in args] if args else get_nobinary(cwd)
    with Pool(processes=MAX_WORKERS) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > 32:
                pending.popleft().get()
        while pending:
            pending.popleft().get()


if __name__ == "__main__":
    raise SystemExit(main())
