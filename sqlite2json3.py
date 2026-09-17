#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path


def convert_sqlite_to_json(db_path: Path):
    pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <database.db>")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    output_path = input_path.with_suffix(".json")
    try:
        convert_sqlite_to_json(input_path)
        print(f"Successfully converted {input_path} to {output_path}")
    except Exception as e:
        print(f"Error: {e}")
