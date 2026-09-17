#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from pathlib import Path


def speak_text(text: str) -> None:
    subprocess.run(["termux-tts-speak", text], check=True)


def read_text_file(path: str) -> str:
    path = Path(path)
    if not path.exists():
        msg = "error: file not found"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, max_chars=3000):
    chunks = []
    current = ""
    for paragraph in text.splitlines():
        if len(current) + len(paragraph) + 1 > max_chars:
            if current:
                chunks.append(current.strip())
                current = paragraph
            else:
                chunks.append(paragraph[:max_chars])
                current = paragraph[max_chars:]
        else:
            current += paragraph + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


def text_file_to_speech(path: str) -> None:
    text = read_text_file(path)
    chunks = chunk_text(text)
    for i, chunk in enumerate(chunks, start=1):
        print(f"Speaking chunk {i}/{len(chunks)}...")
        speak_text(chunk)


if __name__ == "__main__":
    text_file_to_speech("/sdcard/Download/sample.txt")
