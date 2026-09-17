#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path


def clean_file(filename: str) -> None:
    try:
        with Path(filename).open(encoding="utf-8") as f:
            lines = f.readlines()
        cleaned_lines = []
        for line in lines:
            cleaned_line = "".join(
                ch
                for ch in line
                if unicodedata.category(ch)[0] != "C" or ch in "\n\r\t"
            )
            cleaned_lines.append(cleaned_line)
        with Path(filename).open("w", encoding="utf-8") as f:
            f.writelines(cleaned_lines)
        print(f"Successfully cleaned: {filename}")
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_text.py <filename>")
    else:
        target_file = sys.argv[1]
        clean_file(target_file)
