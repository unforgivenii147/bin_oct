#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

from dh import cprint


def is_persian_word(word):
    persian_pattern = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
    return bool(persian_pattern.search(word))


def is_english_word(word):
    english_pattern = re.compile(r"[a-zA-Z]")
    return bool(english_pattern.search(word))


def check_file_format(data):
    if not data or not isinstance(data, dict):
        return False, [], []
    sample_keys = list(data.keys())[:5]
    sample_values = list(data.values())[:5]
    persian_keys = sum(1 for k in sample_keys if is_persian_word(k))
    english_values = sum(
        1 for v in sample_values if isinstance(v, str) and is_english_word(v)
    )
    is_correct = (
        persian_keys >= len(sample_keys) * 0.5
        and english_values >= len(sample_values) * 0.5
    )
    return is_correct, sample_keys, sample_values


def merge_json_files(directory=".", output_file="faen.json"):
    merged_data = OrderedDict()
    duplicate_keys = {}
    skipped_files = []
    file_count = 0
    total_records = 0
    json_files = sorted(Path(directory).glob("*.json"))
    json_files = [f for f in json_files if f.name != output_file]
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                print(f"⚠️  Skipping {json_file.name}: Not a dictionary format")
                skipped_files.append((json_file.name, "Not a dictionary"))
                continue
            is_correct_format, sample_keys, sample_values = check_file_format(data)
            if not is_correct_format:
                cprint(
                    f"❌ Skipping {json_file.name}: Wrong format (English keys detected)"
                )
                print(f"   Sample keys: {sample_keys}")
                print(f"   Sample values: {sample_values}")
                skipped_files.append((json_file.name, "Wrong format (English keys)"))
                continue
            file_count += 1
            file_records = len(data)
            total_records += file_records
            print(f"✅ Processing: {json_file.name} ({file_records} records)")
            for persian_word, english_translation in data.items():
                if not is_persian_word(persian_word):
                    print(f"   ⚠️  Skipping entry '{persian_word}': Key is not Persian")
                    continue
                if persian_word in merged_data:
                    if persian_word not in duplicate_keys:
                        duplicate_keys[persian_word] = []
                    duplicate_keys[persian_word].append(
                        {
                            "existing": merged_data[persian_word],
                            "duplicate": english_translation,
                            "file": json_file.name,
                        }
                    )
                else:
                    merged_data[persian_word] = english_translation
            json_file.unlink()
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing {json_file.name}: {e}")
            skipped_files.append((json_file.name, f"JSON parsing error: {e}"))
        except Exception as e:
            print(f"❌ Error reading {json_file.name}: {e}")
            skipped_files.append((json_file.name, f"Read error: {e}"))
    print("\n" + "=" * 40)
    print(f"💾 Saving merged data to {output_file}...")
    sorted_data = OrderedDict(sorted(merged_data.items()))
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=2)
    print("\n" + "=" * 40)
    print("📊 MERGE REPORT")
    print("=" * 40)
    print(f"Files processed successfully: {file_count}")
    print(f"Files skipped: {len(skipped_files)}")
    if skipped_files:
        print("\n🚫 SKIPPED FILES:")
        print("-" * 40)
        for filename, reason in skipped_files:
            print(f"  • {filename}: {reason}")
    print(f"\nTotal records found (from valid files): {total_records}")
    print(f"Unique records saved: {len(merged_data)}")
    print(f"Duplicate keys found: {len(duplicate_keys)}")
    if duplicate_keys:
        print("\n🔍 DUPLICATE KEYS DETAILS:")
        print("-" * 40)
        for key, duplicates in duplicate_keys.items():
            print(f"\nKey: '{key}'")
            for dup in duplicates:
                print(f"  • Existing: '{dup['existing']}'")
                print(f"    Duplicate: '{dup['duplicate']}' (from {dup['file']})")
    print("\n✅ Merge complete!")


def main():
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        directory = "."
    output_file = "final_faen.json"
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if not os.path.exists(directory):
        print(f"❌ Directory '{directory}' does not exist.")
        sys.exit(1)
    print("🔄 Starting JSON merge process...")
    print(f"📁 Source directory: {os.path.abspath(directory)}")
    print(f"📄 Output file: {output_file}")
    print("=" * 40)
    merge_json_files(directory, output_file)


if __name__ == "__main__":
    main()
