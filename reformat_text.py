#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_LEN = 120
BREAK_PUNCTS = [",", ";", ":", "?"]


def split_sentences(text: str):
    pattern = re.compile(r"[^.!]+[.!]", re.MULTILINE | re.DOTALL)
    sentences = pattern.findall(text)
    return [s.strip() for s in sentences if s.strip()]


def break_long_sentence(sentence: str, max_len: int = MAX_LEN):
    parts = []
    while len(sentence) > max_len:
        break_pos = -1
        window = sentence[:max_len]
        for p in BREAK_PUNCTS:
            pos = window.rfind(p)
            break_pos = max(break_pos, pos)
        if break_pos < 0:
            break_pos = max_len
        parts.append(sentence[: break_pos + 1].strip())
        sentence = sentence[break_pos + 1 :].strip()
    if sentence:
        parts.append(sentence.strip())
    return parts


def restructure_paragraph(paragraph: str) -> str:
    sentences = split_sentences(paragraph)
    lines = []
    for s in sentences:
        lines.extend(break_long_sentence(s, MAX_LEN))
    return "\n".join(lines)


def restructure_file(path: Path) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    text = path.read_text(encoding="utf-8", errors="ignore")
    backup.write_text(text, encoding="utf-8")
    paragraphs = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    new_paragraphs = [restructure_paragraph(p) for p in paragraphs]
    new_text = "\n\n".join(new_paragraphs) + "\n"
    path.write_text(new_text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python restructure_text.py <filename>")
        sys.exit(1)
    file_arg = Path(sys.argv[1])
    if not file_arg.exists():
        print(f"Error: file '{file_arg}' does not exist.")
        sys.exit(1)
    restructure_file(file_arg)


if __name__ == "__main__":
    raise SystemExit(main())
