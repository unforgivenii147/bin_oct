#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3
from markdownify import markdownify


def process_file(path) -> None:
    path = Path(path)
    md_path = path.with_suffix(".md")
    content = path.read_text(encoding="utf8")
    markdownify(content)
    md_path.write_text(md_content, encoding="utf-8")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p, ext=[".html"]))
    else:
        files.extend(get_files(p, ext=[".html"]))
    mpf3(process_file, files)
