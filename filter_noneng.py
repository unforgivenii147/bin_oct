#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gcld3


def process_file_lines(input_path: Path, move_mode: bool):
    if not input_path.is_file():
        print(f"❌ Error: The file '{input_path}' does not exist or is not a file.")
        sys.exit(1)
    detector = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=1000)
    try:
        lines = input_path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        sys.exit(1)
    english_lines = []
    non_english_lines = []
    print(f"🔍 Analyzing {len(lines)} lines from '{input_path.name}'...")
    print("-" * 40)
    for i, line in enumerate(lines, start=1):
        clean_line = line.strip()
        if not clean_line:
            english_lines.append(line)
            continue
        result = detector.FindLanguage(clean_line)
        if result.language == "en" and result.is_reliable:
            english_lines.append(line)
        else:
            non_english_lines.append(line)
            lang_info = (
                f"[{result.language.upper()} (Prob: {result.probability:.2f})]"
                if result.language != "und"
                else "[UNKNOWN]"
            )
            print(f"Line {i} {lang_info}: {clean_line}")
    print("-" * 40)
    print(f"📊 Summary: Found {len(non_english_lines)} non-English lines.")
    if move_mode:
        if not non_english_lines:
            print("ℹ️  No non-English lines found to extract. Base file left unchanged.")
            return
        output_path = Path("noneng.txt")
        try:
            output_path.write_text(
                "\n".join(non_english_lines) + "\n", encoding="utf-8"
            )
            print(f"💾 Extracted lines written safely to: {output_path.resolve()}")
            input_path.write_text("\n".join(english_lines) + "\n", encoding="utf-8")
            print("🔄 Original file updated in-place (non-English elements removed).")
        except Exception as e:
            print(f"❌ Error during file write operations: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Scan text files and isolate non-English strings using Google CLD3."
    )
    parser.add_argument(
        "file", type=str, help="The target file path to inspect line by line."
    )
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Move identified non-English lines to noneng.txt and drop them from the source file.",
    )
    args = parser.parse_args()
    process_file_lines(Path(args.file), args.move)


if __name__ == "__main__":
    raise SystemExit(main())
