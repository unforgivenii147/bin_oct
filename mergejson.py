#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import sys


def deep_merge(dict1, dict2):
    if dict1 is None:
        return dict2
    if dict2 is None:
        return dict1
    merged = dict1.copy()
    for key, value in dict2.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_json_files(input_files, output_file):
    merged_data = None
    for path in input_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"Error: File '{path}' not found.")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"Error: File '{path}' contains invalid JSON.")
            sys.exit(1)
        if merged_data is None:
            merged_data = data
            continue
        if type(merged_data) != type(data):
            print(
                f"Error: Type mismatch. '{input_files[0]}' is a {type(merged_data).__name__}, "
                f"but '{path}' is a {type(data).__name__}. Cannot merge."
            )
            sys.exit(1)
        if isinstance(merged_data, list):
            merged_data.extend(data)
        elif isinstance(merged_data, dict):
            merged_data = deep_merge(merged_data, data)
        else:
            print(f"Error: Unsupported top-level JSON type: {type(data).__name__}")
            sys.exit(1)
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully merged {len(input_files)} files into '{output_file}'.")
    except OSError as e:
        print(f"Error writing to output file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Merge two or more JSON files into one."
    )
    parser.add_argument(
        "inputs", nargs="+", help="Paths to the input JSON files (minimum 2)"
    )
    parser.add_argument(
        "-o", "--output", required=True, help="Path for the merged output JSON file"
    )
    args = parser.parse_args()
    if len(args.inputs) < 2:
        print("Error: Please provide at least two input files to merge.")
        sys.exit(1)
    merge_json_files(args.inputs, args.output)
