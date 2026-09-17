#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import string
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>")
        sys.exit(1)
    input_file = sys.argv[1]
    if not Path(input_file).is_file():
        print(f"Error: file not found: {input_file}")
        sys.exit(1)
    Path("output").mkdir(exist_ok=True, parents=True)
    files = {
        letter: Path(os.path.join("output", f"{letter}.txt")).open(
            "w", encoding="utf-8"
        )
        for letter in string.ascii_lowercase
    }
    try:
        with Path(input_file).open(encoding="utf-8") as f:
            for line in f:
                stripped = line.lstrip()
                if not stripped:
                    continue
                first_char = stripped[0].lower()
                if first_char in files:
                    files[first_char].write(line)
    finally:
        for f in files.values():
            f.close()


if __name__ == "__main__":
    raise SystemExit(main())
