#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys

import whisper


def m4a_to_text_whisper(input_file, output_file="out.txt"):
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        sys.exit(1)
    print("Loading Whisper model...")
    model = whisper.load_model("base")
    print(f"Processing: {input_file}")
    result = model.transcribe(input_file)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result["text"])
    print(f"✓ Transcription saved to: {output_file}")
    print(
        f"Transcribed text:\n{result['text'][:200]}..."
        if len(result["text"]) > 200
        else f"Transcribed text:\n{result['text']}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python m4a_to_text.py <input_file.m4a>")
        sys.exit(1)
    m4a_to_text_whisper(sys.argv[1])
