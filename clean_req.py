#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

_VERSION_OP_RE = re.compile(r"\s*(?:===|==|!=|>=|<=|~=|>|<)\s*")


def clean_requirement(line: str) -> str:
    line = line.split("#", 1)[0].strip()
    if not line:
        return ""
    line = line.split(";", 1)[0].strip()
    if not line:
        return ""
    line = re.sub(r"\[.*?\]", "", line).strip()
    if not line:
        return ""
    parts = _VERSION_OP_RE.split(line, maxsplit=1)
    return parts[0].strip()


def group_key(name: str) -> tuple[int, str]:
    first = name[0]
    if first.isupper():
        return 0, name
    if first.islower():
        return 1, name
    return 2, name


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} requirements.txt", file=sys.stderr)
        sys.exit(1)
    fname = sys.argv[1]
    try:
        with Path(fname).open(encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File '{fname}' not found.", file=sys.stderr)
        sys.exit(1)
    cleaned = []
    seen = set()
    for line in lines:
        c = clean_requirement(line)
        if c and c not in seen:
            cleaned.append(c)
            seen.add(c)
    cleaned = sorted(cleaned, key=group_key)
    with Path(fname).open("w", encoding="utf-8") as f:
        f.writelines(item + "\n" for item in cleaned)
    print("\n=== Cleaned Requirements ===")
    for item in cleaned:
        print(item)


if __name__ == "__main__":
    raise SystemExit(main())
