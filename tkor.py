#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deep_translator import GoogleTranslator

CHUNK_SIZE = 2000


def read_text_file(path: Path) -> str:
    allowed = {".txt", ".md", ".csv", ".json", ".py"}
    ext = path.suffix.lower()
    if ext not in allowed:
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, size: int = 32768) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunks(chunks: list[str]) -> str:
    translator = GoogleTranslator(source="ko", target="en")
    translated_parts = [translator.translate(chunk) for chunk in chunks]
    return "".join(translated_parts)


def write_text_file(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def build_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_eng{input_path.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate Korean → English using chunked deep-translator."
    )
    parser.add_argument("input_path", type=str, help="Path to input file.")
    parser.add_argument(
        "-g", "--game", type=str, default=None, help="Optional game argument."
    )
    args = parser.parse_args()
    in_path = Path(args.input_path)
    if not in_path.exists():
        print(f"Error: File not found: {in_path}", file=sys.stderr)
        sys.exit(1)
    try:
        original_text = read_text_file(in_path)
    except Exception as exc:
        print(f"Read error: {exc}", file=sys.stderr)
        sys.exit(1)
    chunks = chunk_text(original_text)
    try:
        translated_text = translate_chunks(chunks)
    except Exception as exc:
        print(f"Translation error: {exc}", file=sys.stderr)
        sys.exit(1)
    out_path = build_output_path(in_path)
    try:
        write_text_file(out_path, translated_text)
    except Exception as exc:
        print(f"Write error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Saved translated file → {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
