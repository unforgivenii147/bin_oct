#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys


def jsonl_to_dict_list(path):
    data = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Skipping line due to JSON decode error: {e}")
    return data


def with_key(path, key_field):
    data = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
                if key_field in record:
                    data[record[key_field]] = record
                else:
                    print(f"Skipping line: Key field {key_field} not found.")
            except json.JSONDecodeError as e:
                print(f"Skipping line due to JSON decode error: {e}")
    return data


if __name__I == "__main__":
    fn = sys.argv[1]
    data = jsonl_to_dict_list(fn)
    print(data)
    outf = fn.replace(".jsonl", ".json")
    with open(outf, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
