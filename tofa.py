#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from pathlib import Path

from deep_translator import GoogleTranslator
from tqdm import tqdm

MAX_CHARS = 5000


def get_output_filename(input_file: str) -> Path:
    path = Path(input_file)
    stem = path.stem
    suffix = path.suffix
    return path.parent / f"{stem}_fa{suffix}"


def load_file(input_file) -> str:
    encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
    for encoding in encodings:
        try:
            return Path(input_file).read_text(encoding=encoding)
        except (OSError, UnicodeDecodeError):
            continue
    msg = f"Could not read file {input_file} with any encoding"
    raise OSError(msg)


def save_file(output_file: Path, content: str) -> None:
    Path(output_file).write_text(content, encoding="utf-8")


def find_chunk_boundary(text, max_chars):
    if len(text) <= max_chars:
        return len(text)
    search_area = text[:max_chars]
    for delimiter in ["\n", "\r\n", ".  ", "!  ", "?  ", "; ", ", ", " "]:
        last_pos = search_area.rfind(delimiter)
        if last_pos > 0:
            return last_pos + len(delimiter)
    last_space = search_area.rfind(" ")
    if last_space > 0:
        return last_space + 1
    return max_chars


def chunk_text(text: str, max_chars: int):
    chunks = []
    pos = 0
    while pos < len(text):
        remaining = text[pos:]
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        chunk_end = find_chunk_boundary(remaining, max_chars)
        chunks.append(remaining[:chunk_end])
        pos += chunk_end
    return chunks


def translate_chunk(text: str, source_lang="auto"):
    for attempt in range(3):
        try:
            translator = GoogleTranslator(source=source_lang, target="fa")
            translated = translator.translate(text)
            return translated, source_lang
        except Exception as e:
            print(f"[WARN] Translation failed (attempt {attempt + 1}/3): {e}")
            time.sleep(1 + attempt)
    msg = "Failed to translate chunk after 3 attempts"
    raise Exception(msg)


def translate_file(input_file: str, source_lang: str = "auto") -> str:
    print(f"[INFO] Reading file: {input_file}")
    content = load_file(input_file)
    content_length = len(content)
    print(f"[INFO] File size: {content_length} characters")
    if content_length <= MAX_CHARS:
        print(f"[INFO] Content fits in single request ({content_length} chars)")
        print("[INFO] Translating...")
        translated, detected_lang = translate_chunk(content, source_lang)
        print(f"[INFO] Detected language: {detected_lang}")
        return translated
    chunks = chunk_text(content, MAX_CHARS)
    total_chunks = len(chunks)
    print(f"[INFO] Content split into {total_chunks} chunks")
    print(f"[INFO] Chunk sizes: {[len(c) for c in chunks]}")
    translated_chunks = []
    detected_lang = None
    pbar = tqdm(total=total_chunks, desc="Translating", unit="chunk")
    try:
        for i, chunk in enumerate(chunks):
            print(
                f"\n[INFO] Translating chunk {i + 1}/{total_chunks} ({len(chunk)} chars)..."
            )
            try:
                translated_chunk, detected_lang = translate_chunk(chunk, source_lang)
                translated_chunks.append(translated_chunk)
                pbar.update(1)
            except Exception as e:
                print(f"[ERROR] Failed to translate chunk {i + 1}: {e}")
                pbar.update(1)
                translated_chunks.append(chunk)
    finally:
        pbar.close()
    result = "".join(translated_chunks)
    print(f"\n[INFO] Detected language: {detected_lang}")
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file> [source_language]")
        print("\nExamples:")
        print(f"  {sys.argv[0]} document.txt")
        print(f"  {sys.argv[0]} file.txt de")
        print(f"  {sys.argv[0]}document.txt en")
        print(
            "\nSupported languages:  auto, en ,fa , fr, de, es, it, pt, ru, zh, ja, ko, ar, etc."
        )
        sys.exit(1)
    input_file = sys.argv[1]
    source_lang = sys.argv[2] if len(sys.argv) > 2 else "auto"
    if not Path(input_file).exists():
        print(f"[ERROR] File not found: {input_file}")
        sys.exit(1)
    output_file = get_output_filename(input_file)
    if Path(output_file).exists():
        print(f"[INFO] Output file already exists: {output_file}")
        print(f"[INFO] Skipping translation (delete {output_file} to re-translate)")
        sys.exit(0)
    print(f"[INFO] Input:   {input_file}")
    print(f"[INFO] Output: {output_file}")
    print(f"[INFO] Source language: {source_lang}")
    print()
    try:
        translated_content = translate_file(input_file, source_lang)
        print(f"\n[INFO] Saving result to: {output_file}")
        save_file(output_file, translated_content)
        print("\n[SUCCESS] Translation complete!")
        print(f"[INFO] Output file: {output_file}")
        print(f"[INFO] Output size: {len(translated_content)} characters")
    except Exception as e:
        print(f"\n[ERROR] Translation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
