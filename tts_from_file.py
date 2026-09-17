#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def speak_text(text: str) -> None:
    subprocess.run(["termux-tts-speak", text], check=True)


def chunk_text(text: str, max_chars: int = 3000):
    lines = text.splitlines()
    chunks = []
    current = ""
    for line in lines:
        candidate = (current + "\n" + line).strip() if current else line.strip()
        if not candidate:
            continue
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(line) > max_chars:
                chunks.append(line[:max_chars])
                line = line[max_chars:]
            current = line.strip()
    if current.strip():
        chunks.append(current)
    return chunks


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tts_from_file.py /path/to/file.txt")
        sys.exit(1)
    path = sys.argv[1]
    path = Path(path)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    text = path.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_text(text)
    print(f"Loaded {path}. Total chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks, start=1):
        print(f"Speaking chunk {i}/{len(chunks)} (chars={len(chunk)})...")
        speak_text(chunk)


if __name__ == "__main__":
    raise SystemExit(main())
