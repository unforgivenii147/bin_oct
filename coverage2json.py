#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def coverage_to_json(
    input_file: str = ".coverage", output_file: str = "coverage.json"
) -> None:
    db_path = Path(input_file)
    out_path = Path(output_file)
    if not db_path.exists():
        print(f"Error: {input_file} not found", file=sys.stderr)
        sys.exit(1)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            print("Warning: No tables found in database", file=sys.stderr)
        data = {}
        for table_name in tables:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            data[table_name] = [
                {k: serialize_value(v) for k, v in dict(row).items()} for row in rows
            ]
        conn.close()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Converted {input_file} → {output_file}")
    except sqlite3.DatabaseError as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"File I/O error: {e}", file=sys.stderr)
        sys.exit(1)


def serialize_value(value: Any) -> Any:
    if value is None:
        return None
    elif isinstance(value, (str, int, float, bool)):
        return value
    elif isinstance(value, bytes):
        return f"<BLOB:{value.hex()}>"
    else:
        return str(value)


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    input_file = ".coverage"
    output_file = "coverage.json"
    if len(args) >= 1:
        input_file = args[0]
    if len(args) >= 2:
        output_file = args[1]
    coverage_to_json(input_file, output_file)


if __name__ == "__main__":
    raise SystemExit(main())
