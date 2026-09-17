#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
from pathlib import Path


def resolve_imports(content: str, cwd: Path) -> str:
    folder_name = Path(cwd).name
    content = re.sub(
        r"from \. import ([a-zA-Z0-9_]+)", f"from {folder_name} import \\1", content
    )
    content = re.sub(
        r"from \.([a-zA-Z0-9_]+) import ([a-zA-Z0-9_]+)",
        f"from {folder_name}.\\1 import \\2",
        content,
    )
    return re.sub(r"import \.", f"import {folder_name}", content)


def merge_python_files() -> None:
    cwd = Path.cwd()
    folder_name = Path(cwd).name
    output_filename = f"{folder_name}.py"
    py_files = [
        f for f in os.listdir(cwd) if f.endswith(".py") and f != output_filename
    ]
    py_files.sort()
    with Path(output_filename).open("w", encoding="utf-8") as outfile:
        for py_file in py_files:
            with Path(py_file).open(encoding="utf-8") as infile:
                content = infile.read()
                content = resolve_imports(content, cwd)
                outfile.write(content)
    print(f"Merged {len(py_files)} files into {output_filename}")


if __name__ == "__main__":
    merge_python_files()
