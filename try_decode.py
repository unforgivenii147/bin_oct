#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

COMMON_ENCODINGS = [
    "utf-8",
    "utf-8-sig",
    "latin-1",
    "cp1252",
    "cp1251",
    "cp1256",
    "iso-8859-1",
    "iso-8859-2",
    "iso-8859-5",
    "iso-8859-6",
    "iso-8859-7",
    "iso-8859-8",
    "iso-8859-9",
    "cp437",
    "cp850",
    "cp866",
    "mac_roman",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
    "gbk",
    "gb2312",
    "big5",
    "shift_jis",
    "euc_jp",
    "euc_kr",
]
EXTRA_ENCODINGS = [
    "ascii",
    "cp775",
    "cp852",
    "cp855",
    "cp857",
    "cp860",
    "cp861",
    "cp862",
    "cp863",
    "cp865",
    "cp869",
    "cp874",
    "cp949",
    "cp950",
    "koi8_r",
    "koi8_u",
    "mac_cyrillic",
    "mac_greek",
    "mac_iceland",
    "mac_latin2",
]


def try_decode(file_content: bytes, encoding: str):
    try:
        decoded = file_content.decode(encoding)
        return (True, decoded)
    except (UnicodeDecodeError, LookupError):
        return (False, None)


def get_first_chunk(text: str, chunk_size: int = 500) -> str:
    if len(text) <= chunk_size:
        return text
    return text[:chunk_size] + "...\n[truncated...]"


def decode_file(path: str, output_path: str | None = None, show_chunk: int = 500):
    path = Path(path)
    if not path.exists():
        print(f"Error: File '{path}' not found.")
        return False
    try:
        with open(path, "rb") as f:
            file_content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return False
    print(f"Processing: {path.name}")
    print(f"File size: {len(file_content)} bytes")
    print("-" * 40)
    encodings_to_try = COMMON_ENCODINGS + EXTRA_ENCODINGS
    successful_encodings = []
    successful_text = None
    best_encoding = None
    for encoding in encodings_to_try:
        success, decoded_text = try_decode(file_content, encoding)
        if success:
            successful_encodings.append(encoding)
            if successful_text is None:
                successful_text = decoded_text
                best_encoding = encoding
            print(f"✓ {encoding:15} - Successfully decoded!")
            if show_chunk > 0:
                chunk = get_first_chunk(decoded_text, show_chunk)
                preview = chunk.replace("\n", "\n  ").replace("\r", r"\r")
                print(f"  Preview:\n  {preview}\n")
    print("-" * 40)
    if not successful_encodings:
        print("❌ No encoding could decode this file.")
        return False
    print(f"\n✅ Found {len(successful_encodings)} successful encoding(s):")
    for enc in successful_encodings:
        print(f"  - {enc}")
    print(f"\n📌 Best match: {best_encoding}")
    if len(successful_encodings) > 1:
        print(
            "\nMultiple encodings found. Which one should be used for UTF-8 conversion?"
        )
        print("0: Cancel")
        for i, enc in enumerate(successful_encodings, 1):
            print(f"{i}: {enc}")
        try:
            choice = input(f"Enter choice (1-{len(successful_encodings)}): ").strip()
            if not choice:
                choice = "1"
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(successful_encodings):
                chosen_encoding = successful_encodings[choice_idx]
            else:
                print("Invalid choice. Using best match.")
                chosen_encoding = best_encoding
        except ValueError:
            print("Invalid input. Using best match.")
            chosen_encoding = best_encoding
    else:
        chosen_encoding = best_encoding
    try:
        decoded_text = file_content.decode(chosen_encoding)
    except Exception as e:
        print(f"Error decoding with {chosen_encoding}: {e}")
        return False
    if output_path is None:
        output_path = path.stem + "_utf8" + path.suffix
        if path.suffix.lower() == ".txt":
            output_path = path.stem + "_utf8.txt"
        else:
            output_path = path.parent / f"{path.stem}_utf8{path.suffix}"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(decoded_text)
        print(f"\n💾 Saved UTF-8 version to: {output_path}")
        print(f"   Original encoding: {chosen_encoding}")
        print(f"   Characters decoded: {len(decoded_text)}")
        return True
    except Exception as e:
        print(f"Error saving file: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python decode_file.py <path> [output_path]")
        print("Example: python decode_file.py mystery.txt")
        print("Example: python decode_file.py mystery.txt decoded.txt")
        sys.exit(1)
    path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    decode_file(path, output_path)


if __name__ == "__main__":
    raise SystemExit(main())
