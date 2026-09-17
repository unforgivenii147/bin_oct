#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from pathlib import Path


def compress_python_file(path: str) -> None:
    content = Path(path).read_text(encoding="utf-8")
    content = re.sub(r"\"\"\".*?\"\"\"|'''.*?'''", "", content, flags=re.DOTALL)
    content = re.sub(r"#.*", "", content)
    lines = content.splitlines()
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    content = "\n".join(non_empty_lines)
    Path(path).write_text(content, encoding="utf-8")


def compress_python_files_in_directory(directory: str = ".") -> None:
    for filename in os.listdir(directory):
        if filename.endswith(".py"):
            path = os.path.join(directory, filename)
            print(f"Compressing {path}...")
            compress_python_file(path)
    print("Compression complete.")


if __name__ == "__main__":
    compress_python_files_in_directory(".")
