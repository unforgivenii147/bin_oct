#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python check_dups.py <const_file.py>")
        sys.exit(1)
    src_path = Path(sys.argv[1])
    if not src_path.exists():
        print(f"File not found: {src_path}")
        sys.exit(1)
    dup_path = src_path.parent / "dup_const.py"
    assign_re = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=")
    lines = src_path.read_text().splitlines(keepends=True)
    first_seen = {}
    duplicates = []
    for i, line in enumerate(lines):
        match = assign_re.match(line)
        if match:
            name = match.group(1)
            if name not in first_seen:
                first_seen[name] = i
            else:
                duplicates.append((i, line))
    if not duplicates:
        print("No duplicates found.")
        return
    modified_lines = [
        line for idx, line in enumerate(lines) if idx not in {d[0] for d in duplicates}
    ]
    src_path.write_text("".join(modified_lines))
    with dup_path.open("a") as f:
        f.write(f"\n# Duplicate declarations from {src_path.name}\n")
        for _, dup_line in duplicates:
            f.write(dup_line)
    print("Kept the first declaration of each constant.")
    print(f"Moved {len(duplicates)} duplicate declarations to {dup_path}")
    print(f"Updated {src_path} in place.")


if __name__ == "__main__":
    raise SystemExit(main())
