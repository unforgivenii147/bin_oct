#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path

import toml


def toml_to_json(fname: str) -> None:
    try:
        with open(fname, encoding="utf-8") as f:
            toml_data = toml.load(f)
        json_fname = Path(fname).with_suffix(".json")
        with open(json_fname, "w", encoding="utf8") as f:
            json.dump(toml_data, f, indent=2, ensure_ascii=False)
        print(f"{fname} -> {json_fname}")
    except FileNotFoundError:
        print(f"Error: The file '{fname}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python toml_to_json_converter.py <path_to_toml_file>")
        sys.exit(1)
    input_file = sys.argv[1]
    toml_to_json(input_file)
