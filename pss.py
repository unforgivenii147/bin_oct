#!/data/data/com.termux/files/home/.local/bin/python
"""
Search PyPI packages from a JSON file by name with fuzzy matching.

Fuzzy mode matches a package if any of these is true:
  - package name starts with the keyword
  - keyword is a substring of the package name
  - Levenshtein similarity with the keyword is > 70%

Results are always sorted by download count (descending).
"""

import json
import sys
from pathlib import Path

JSON_PATH = Path("/sdcard/data/pip.json")
FUZZY_THRESHOLD = 0.70
LIMIT = 20


def load_packages(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [(str(name), int(dl)) for name, dl in data]


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = curr
    return prev[-1]


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    dist = levenshtein(a, b)
    return 1.0 - dist / max(len(a), len(b))


def search(
    packages, keyword: str, fuzzy: bool = False, threshold: float = FUZZY_THRESHOLD
):
    kw = keyword.lower()
    results = []

    for name, downloads in packages:
        lname = name.lower()
        score = None

        if not fuzzy:
            if lname == kw:
                print(f"{name}  {downloads}")
                score = 1.0
        else:
            if lname.startswith(kw):
                print(f"{name}  {downloads}")
                score = 1.0
            elif kw in lname:
                print(f"{name}  {downloads}")
                score = 0.95
            else:
                sim = similarity(kw, lname)
                if sim > threshold:
                    score = sim

        if score is not None:
            results.append((name, downloads, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def format_downloads(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.2f}K"
    return str(n)


def main():
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
    else:
        keyword = input("Search package: ").strip()
        if not keyword:
            print("No keyword given.")
            return

    packages = load_packages(JSON_PATH)
    results = search(packages, keyword)

    if not results:
        print(f"No matches for '{keyword}'.")
        return

    print(f"Found {len(results)} match(es) for '{keyword}':\n")
    print(f"{'Package':<40} {'Downloads':>14} {'Score':>6}")
    print("-" * 62)
    for name, downloads, score in results[:LIMIT]:
        print(f"{name:<40} {format_downloads(downloads):>14} {score:>6.2f}")


if __name__ == "__main__":
    main()
