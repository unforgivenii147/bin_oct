#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from joblib import Parallel, delayed


def is_text_file(path):
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" not in chunk
    except (OSError, PermissionError):
        return False


def search_in_file(path, search_string):
    try:
        if not is_text_file(path):
            return []
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
            if search_string in content:
                return [str(path.relative_to(Path.cwd()))]
    except (OSError, PermissionError, UnicodeDecodeError):
        pass
    return []


def search_in_directory(directory, search_string, n_jobs=-1):
    files = [f for f in directory.rglob("*") if f.is_file()]
    results = Parallel(n_jobs=n_jobs)(
        delayed(search_in_file)(file, search_string) for file in files
    )
    matches = [match for sublist in results for match in sublist]
    return matches


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search_for.py <search_string>")
        sys.exit(1)
    search_string = sys.argv[1]
    current_dir = Path.cwd()
    print(f"Searching for '{search_string}' in text files under: {current_dir}")
    matches = search_in_directory(current_dir, search_string)
    if matches:
        print("\nFound in:")
        for match in matches:
            print(match)
    else:
        print("\nNo matches found.")
