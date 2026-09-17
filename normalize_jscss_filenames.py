#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from pathlib import Path

from dh import unique_path


def normalize_filename(filename) -> str:
    pattern = "(\\.(?:js|css))([?#].*)?$"
    normalized = re.sub(pattern, "\\1", filename, flags=re.IGNORECASE)
    return normalized


def normalize_filenames_in_text(text: str) -> str:
    pattern = "\\b([^\\s<>\\\"\\']*?\\.(?:js|css))([?#][^\\s<>\\\"\\']*)?\\b"

    def replace_match(match):
        return match.group(1)

    normalized_text = re.sub(pattern, replace_match, text, flags=re.IGNORECASE)
    return normalized_text


def normalize_file_contents(path) -> None:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    normalized_content = normalize_filenames_in_text(content)
    with open(path, "w", encoding="utf-8") as f:
        f.write(normalized_content)
    print(f"Processed: {path}")


def normalize_filenames_batch(directory: Path) -> None:
    processed_count = 0
    for root, _dirs, files in os.walk(directory):
        for file in files:
            if (".js" in file or ".css" in file) and (
                not file.endswith((".js", ".css"))
            ):
                path = Path(root) / file
                if path.suffix == ".json":
                    continue
                try:
                    new_name = normalize_filename(file)
                    new_path = path.with_name(new_name)
                    if new_path.exists():
                        new_path = unique_path(new_path)
                    print(f"{path.name}->{new_path.name}")
                    path.rename(new_path)
                    processed_count += 1
                except Exception as e:
                    print(f"Error processing {path}: {e}")
    print(f"\nProcessed {processed_count} files")


if __name__ == "__main__":
    cwd = Path.cwd()
    normalize_filenames_batch(cwd)
