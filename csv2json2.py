#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python csv_to_json.py <input.csv>")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    output_path = input_path.with_suffix(".json")
    with open(input_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        data = list(reader)
    with open(output_path, mode="w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
