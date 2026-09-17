#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path
from secrets import randbelow


def file_to_json(path: Path, delimiter: str):
    result = {}
    seenkeys = set()
    seenvals = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if delimiter not in line:
                    delimiter = "\t"
                    print(line)
                    input("press any key ...")
                parts = line.split(delimiter, 1)
                if len(parts) != 2:
                    print(
                        f"Warning: Line {line_num} doesn't contain delimiter '{delimiter}': {line!r}",
                        file=sys.stderr,
                    )
                    continue
                key, value = parts
                key = key.strip()
                value = int(value.lstrip().strip())
                if key not in seenkeys:
                    seenkeys.add(key)
                else:
                    print(f"repeated key: {key}")
                if value not in seenvals:
                    seenvals.add(value)
                else:
                    while True:
                        value = int(randbelow(22704))
                        if value not in seenvals:
                            break
                        else:
                            print("repeated random")
                            continue
                result[key] = int(value)
    except FileNotFoundError:
        print(f"Error: File '{path}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)
    keys = list(seenkeys)
    with open("words", "w") as f:
        for key in keys:
            f.write(f"{key}\n")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <filename> <delimiter>", file=sys.stderr)
        sys.exit(1)
    filename = Path(sys.argv[1])
    delimiter = sys.argv[2]
    result = file_to_json(filename, delimiter)
    jsonfile = filename.with_suffix(".json")
    with jsonfile.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
