#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import time

import pysrt
from deep_translator import GoogleTranslator


def translate_srt(input_file, source_lang, target_lang):
    subs = pysrt.open(input_file, encoding="utf-8")
    translator = GoogleTranslator(source=source_lang, target=target_lang)
    batch = []
    current_batch_text = []
    current_char_count = 0
    MAX_CHARS = 2000
    print("Preparing translation batches...")
    batches = []
    current_batch = []
    for sub in subs:
        if current_char_count + len(sub.text) > MAX_CHARS and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_char_count = 0
        current_batch.append(sub)
        current_char_count += len(sub.text)
    if current_batch:
        batches.append(current_batch)
    print(f"Translating {len(batches)} batches...")
    for i, batch in enumerate(batches):
        try:
            text_to_translate = " ||| ".join([sub.text for sub in batch])
            translated_blob = translator.translate(text_to_translate)
            translated_lines = translated_blob.split(" ||| ")
            for j, sub in enumerate(batch):
                sub.text = (
                    translated_lines[j] if j < len(translated_lines) else sub.text
                )
            print(f"Processed batch {i + 1}/{len(batches)}")
            time.sleep(1)
        except Exception as e:
            print(f"Error in batch {i}: {e}")
    output_file = f"translated_{os.path.basename(input_file)}"
    subs.save(output_file, encoding="utf-8")
    print(f"Translation complete! Saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate SRT files in chunks.")
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-s", "--source", required=True)
    parser.add_argument("-t", "--target", required=True)
    args = parser.parse_args()
    translate_srt(args.input, args.source, args.target)
