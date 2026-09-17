#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def csv_to_json_map(csv_file: str) -> None:
    csv_path = Path(csv_file)
    if not csv_path.exists():
        print(f"Error: file not found: {csv_path}")
        sys.exit(1)
    json_path = csv_path.with_suffix(".json")
    result = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header or len(header) < 2:
            print("Error: CSV must have at least two columns")
            sys.exit(1)
        for row in reader:
            if len(row) < 2:
                continue
            key = row[0].strip()
            value = row[1].strip()
            if key:
                result[key] = value
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Converted : {csv_path} → {json_path}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file.csv>")
        sys.exit(1)
    csv_to_json_map(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
