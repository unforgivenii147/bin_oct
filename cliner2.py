#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

LOG_EXT = ".log"
PATTERNS = [
    r"\^\[",
    r"\[[\dA-Z;]+m",
    r"\[\d+[A-Z]",
    r"\[[\dA-Z;]+",
    r"\^M",
    r"\(B",
    r"\(0",
    r"\x1b\[[0-9;]*[A-Za-z]",
    r"\x1b\([0-9AB]",
    r"\r",
    r"\x0f",
    r"\x0e",
]


def clean_line(line: str) -> str:
    cleaned = line
    for pattern in PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    return re.sub(r" {2,}", " ", cleaned)


def clean_file(path: Path) -> None:
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        cleaned_lines = [clean_line(line) for line in lines]
        with Path(path).open("w", encoding="utf-8") as f:
            f.writelines(cleaned_lines)
        print(f"✓ Cleaned: {path}")
    except Exception as e:
        print(f"✗ Error processing {path}: {e}")


def main() -> None:
    cwd = Path.cwd()
    log_files = list(cwd.rglob(f"*{LOG_EXT}"))
    if not log_files:
        print(f"No {LOG_EXT} files found.")
        return
    print(f"Found {len(log_files)} log file(s). Cleaning...\n")
    for log_file in log_files:
        clean_file(log_file)
    print(f"\nDone. Processed {len(log_files)} file(s).")


if __name__ == "__main__":
    raise SystemExit(main())
