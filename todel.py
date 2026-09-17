#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import get_nobinary

CHUNK_SIZE = 1024 * 1024


def delete_multiline_string_from_files(search_string: str) -> None:
    cwd = Path.cwd()
    files = get_nobinary(cwd)
    for path in files:
        content = path.read_text(encoding="utf-8")
        if search_string in content:
            new_content = content.replace(search_string, "")
        path.write_text(new_content, encoding="utf-8")


def read_string_to_delete(filename: str = "/sdcard/lic") -> str:
    path = Path(filename)
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    string_to_delete = read_string_to_delete()
    if string_to_delete:
        delete_multiline_string_from_files(string_to_delete)
