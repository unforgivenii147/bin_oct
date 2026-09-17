#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path


def deduplicate_json_object(data):
    if isinstance(data, dict):
        return {k: deduplicate_json_object(v) for k, v in data.items()}
    if isinstance(data, list):
        return [deduplicate_json_object(item) for item in data]
    return data


def deduplicate_json_list(data_list, unique_by=None):
    if not isinstance(data_list, list):
        raise ValueError(msg)
    seen = set()
    new_list = []
    for entry in data_list:
        if not isinstance(entry, dict):
            new_list.append(entry)
            continue
        identifier = (
            entry.get(unique_by) if unique_by else json.dumps(entry, sort_keys=True)
        )
        if identifier not in seen:
            seen.add(identifier)
            new_list.append(entry)
    return new_list


if __name__ == "__main__":
    fn = Path(sys.argv[1])
    with fn.open(encoding="utf-8") as f:
        data = json.load(f)
        cleaned_list = deduplicate_json_list(data, unique_by="src")
        if cleaned_list:
            with fn.open("w", encoding="utf-8") as fo:
                json.dump(cleaned_list, fo, ensure_ascii=False, indent=2)
