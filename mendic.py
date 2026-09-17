#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path


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
    english_keys = sum(1 for k in sample_keys if is_english_word(k))
    persian_values = sum(
        1 for v in sample_values if isinstance(v, str) and is_persian_word(v)
    )
    is_correct = (
        english_keys >= len(sample_keys) * 0.5
        and persian_values >= len(sample_values) * 0.5
    )
    return is_correct, sample_keys, sample_values


def merge_json_files(directory=".", output_file="enfa.json"):
    merged_data = OrderedDict()
    duplicate_keys = {}
    skipped_files = []
    file_count = 0
    total_records = 0
    json_files = sorted(Path(directory).glob("*.json"))
    json_files = [f for f in json_files if f.name != output_file]
    if not json_files:
        print(f"No JSON files found in '{directory}'")
        return
    print(f"Found {len(json_files)} JSON file(s) to process")
    print("=" * 40)
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
                print(
                    f"❌ Skipping {json_file.name}: Wrong format (Persian keys detected)"
                )
                print(f"   Sample keys: {sample_keys}")
                print(f"   Sample values: {sample_values}")
                skipped_files.append((json_file.name, "Wrong format (Persian keys)"))
                continue
            file_count += 1
            file_records = len(data)
            total_records += file_records
            print(f"✅ Processing: {json_file.name} ({file_records} records)")
            for english_word, persian_translation in data.items():
                if not is_english_word(english_word):
                    print(f"   ⚠️  Skipping entry '{english_word}': Key is not English")
                    continue
                if english_word in merged_data:
                    if english_word not in duplicate_keys:
                        duplicate_keys[english_word] = []
                    duplicate_keys[english_word].append(
                        {
                            "existing": merged_data[english_word],
                            "duplicate": persian_translation,
                            "file": json_file.name,
                        }
                    )
                else:
                    merged_data[english_word] = persian_translation
            json_file.unlink()
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing {json_file.name}: {e}")
            skipped_files.append((json_file.name, f"JSON parsing error: {e}"))
        except Exception as e:
            print(f"❌ Error reading {json_file.name}: {e}")
            skipped_files.append((json_file.name, f"Read error: {e}"))
    print("\n" + "=" * 40)
    print(f"💾 Saving merged data to {output_file}...")
    sorted_data = OrderedDict(sorted(merged_data.items(), key=lambda x: x[0].lower()))
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
    if merged_data:
        print("\n📝 SAMPLE OF MERGED DATA:")
        print("-" * 40)
        sample_items = list(merged_data.items())[:5]
        for eng, per in sample_items:
            print(f"  '{eng}': '{per}'")
        if len(merged_data) > 5:
            print(f"  ... and {len(merged_data) - 5} more entries")
    print("\n✅ Merge complete!")


def main():
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
    else:
        directory = Path.cwd()
    output_file = "enfa.json"
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if not directory.exists():
        print(f"❌ Directory '{directory}' does not exist.")
        sys.exit(1)
    print("🔄 Starting JSON merge process...")
    print(f"📁 Source directory: {directory.name}")
    print(f"📄 Output file: {output_file}")
    print("=" * 40)
    merge_json_files(directory, output_file)


if __name__ == "__main__":
    main()
