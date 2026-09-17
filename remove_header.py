#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <json_file>")
        sys.exit(1)
    fn = sys.argv[1]
    with open(fn, encoding="utf-8") as f:
        data = json.load(f)
    transformed = []
    for item in data:
        values = list(item.values())
        if len(values) >= 2:
            transformed.append(
                {f"field_{i + 1}": value for i, value in enumerate(values)}
            )
        else:
            transformed.append(item)
    with open(fn, "w", encoding="utf-8") as fo:
        json.dump(transformed, fo, ensure_ascii=False, indent=2)
    print(f"Successfully transformed {fn}")


if __name__ == "__main__":
    raise SystemExit(main())
