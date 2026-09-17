#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from collections import deque
from multiprocessing import get_context
from pathlib import Path

from dh import get_nobinary
from toolz import compose, frequencies
from toolz.curried import map as _map

CHUNK_SIZE = 1024 * 1024
MAX_QUEUE = 8


def stem(word):
    return word.lower().rstrip(",.|;:'\"").lstrip("'\"")


def process_file(path):
    path = Path(path)
    if path.is_symlink():
        print(f"skipping symlink {path.name}")
    print(f"{path.name}")
    word_count = compose(frequencies, _map(stem), str.split)
    content = path.read_text(encoding="utf-8")
    return word_count(content)


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_nobinary(cwd)
    results = {}
    with get_context("spawn").Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                result = pending.popleft().get()
                for x in result:
                    if x not in results:
                        results[x] = result.get(x)
                    else:
                        results[x] += result.get(x)
        while pending:
            result = pending.popleft().get()
            for x in result:
                if x not in results:
                    results[x] = result.get(x)
                else:
                    results[x] += result.get(x)
    outfile = Path("word_count.json")
    wsorted = [results.get(key) for key in results]
    wsorted = sorted(wsorted, reverse=True)
    word_sorted = {}
    for item in wsorted:
        word_sorted[item] = results.get(item)
    with Path(outfile).open("w", encoding="utf-8") as fo:
        json.dump(word_sorted, fo, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
