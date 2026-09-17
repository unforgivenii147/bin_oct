#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import pytesseract

SUPPORTED_FORMATS = {".png", ".bmp", ".tiff", ".webp", ".jpg", ".jpeg"}


def extract_text(path: str) -> bool:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_FORMATS:
        print(f"Error: '{path.name}' is not a supported image file.")
        return False
    output_path = path.with_suffix(".txt")
    try:
        img = cv2.imread(str(path))
        if img is None:
            print(f"Error: Could not read {path.name}")
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        print(f"Processing '{path.name}'...")
        text = pytesseract.image_to_string(gray)
        if not text.strip():
            print(f"Warning: No text detected in '{path.name}'.")
        Path(output_path).write_text(text, encoding="utf-8")
        print(f"Success! Text saved to '{output_path.name}'")
        return True
    except Exception as e:
        print(f"An error occurred: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <image_file>")
        sys.exit(1)
    if extract_text(sys.argv[1]):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
