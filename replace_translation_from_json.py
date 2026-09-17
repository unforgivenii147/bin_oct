#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def replace_translations(input_file):
    json_file = input_file.with_suffix(".json")
    with open(json_file, "r", encoding="utf-8") as f:
        translations = json.load(f)
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()
    sorted_translations = sorted(
        translations.items(), key=lambda x: len(x[0]), reverse=True
    )
    modified_content = content
    for chinese, english in sorted_translations:
        if chinese != english:
            escaped_chinese = re.escape(chinese)
            modified_content = re.sub(escaped_chinese, english, modified_content)
    with open(input_file, "w", encoding="utf-8") as f:
        f.write(modified_content)
    print(f"Successfully updated {input_file}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <input_file>")
        sys.exit(1)
    input_file = Path(sys.argv[1])
    replace_translations(input_file)
