#!/data/data/com.termux/files/home/.local/bin/python
"""
Extract pkgname values from a JSON file and save them to keys.txt, one per line.

Supports two JSON structures:
  1. Flat object:        {"pkgname": "rust", ...}
  2. List of objects:    [{"pkgname": "rust", ...}, {"pkgname": "python", ...}, ...]

Usage:
    python extract_keys.py <input.json>
"""

import json
import sys


def extract_pkgnames(data):
    """Return a list of 'pkgname' values from a dict or a list of dicts."""
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("JSON root must be an object or a list of objects")

    names = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Item at index {i} is not a JSON object")
        if "pkgname" not in item:
            print(
                f"Warning: item at index {i} has no 'pkgname' key, skipping",
                file=sys.stderr,
            )
            continue
        names.append(item["pkgname"])

    return names


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <input.json>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {input_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {input_file}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        names = extract_pkgnames(data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with open("keys.txt", "w", encoding="utf-8") as f:
        f.writelines(f"{name}\n" for name in names)

    print(f"Wrote {len(names)} pkgname values to keys.txt")


if __name__ == "__main__":
    main()
