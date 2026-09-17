#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

TIMESTAMP_RE = re.compile(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
TAG_RE = re.compile(r"<[^>]+>|{\w+}")


def srt_to_text(srt_path: Path) -> str:
    lines = srt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if TIMESTAMP_RE.match(line):
            continue
        line = TAG_RE.sub("", line)
        out.append(line)
    return "\n".join(out)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: srt2txt.py file.srt [out.txt]")
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".txt")
    text = srt_to_text(src)
    dst.write_text(text, encoding="utf-8")
    print(f"✔ Converted: {src} → {dst}")


if __name__ == "__main__":
    raise SystemExit(main())
