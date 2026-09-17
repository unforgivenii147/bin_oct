#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def restructure_text_file(path: Path) -> None:
    if not path.is_file():
        print(f"Error: File not found at {path}")
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return
    bak_path = path.with_suffix(path.suffix + ".bak")
    try:
        with (
            path.open("r", encoding="utf-8") as src,
            bak_path.open("w", encoding="utf-8") as dst,
        ):
            dst.write(src.read())
        print(f"Backup created at: {bak_path}")
    except Exception as e:
        print(f"Error creating backup file {bak_path}: {e}")
        return
    restructured_lines = []
    paragraphs = content.split("\n\n")
    for paragraph in paragraphs:
        if not paragraph.strip():
            restructured_lines.append("")
            continue
        sentences = re.split(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s+", paragraph)
        for sentence in sentences:
            if not sentence.strip():
                continue
            processed_sentence_parts = []
            current_line_length = 0
            words = sentence.split()
            current_line_words = []
            for word in words:
                potential_line_length = (
                    current_line_length + len(word) + (1 if current_line_words else 0)
                )
                if potential_line_length > 120 and current_line_length > 0:
                    break_point = -1
                    for i, w in enumerate(current_line_words):
                        if w.endswith(","):
                            break_point = i
                    if break_point != -1:
                        processed_sentence_parts.append(
                            " ".join(current_line_words[: break_point + 1])
                        )
                        current_line_words = current_line_words[break_point + 1 :]
                        current_line_length = len(" ".join(current_line_words))
                    else:
                        processed_sentence_parts.append(" ".join(current_line_words))
                        current_line_words = [word]
                        current_line_length = len(word)
                else:
                    current_line_words.append(word)
                    current_line_length = potential_line_length
            if current_line_words:
                processed_sentence_parts.append(" ".join(current_line_words))
            restructured_lines.extend(processed_sentence_parts)
    try:
        with path.open("w", encoding="utf-8") as f:
            f.write("\n".join(restructured_lines))
        print(f"File successfully restructured: {path}")
    except Exception as e:
        print(f"Error writing to file {path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <filename>")
        sys.exit(1)
    filename = sys.argv[1]
    path = Path(filename)
    restructure_text_file(path)
