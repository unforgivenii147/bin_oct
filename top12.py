#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import heapq
import os
from pathlib import Path


def get_top_10_largest_files_optimized(directory: str = "."):
    top_10 = []
    for root, _dirs, files in os.walk(directory):
        for file in files:
            path = Path(root) / file
            if path.is_file():
                try:
                    size = path.stat().st_size
                    if len(top_10) < 10:
                        heapq.heappush(top_10, (size, path))
                    elif size > top_10[0][0]:
                        heapq.heapreplace(top_10, (size, path))
                except OSError:
                    pass
    return sorted(top_10, reverse=True)


if __name__ == "__main__":
    top_10 = get_top_10_largest_files_optimized()
    for size, path in top_10:
        print(f"{size} bytes - {path}")
