#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3
from markdownify import markdownify as md
from readability import Document

remove_orig = True


def process_file(path) -> tuple[Path, bool]:
    path = Path(path)
    md_file = path.with_suffix(".md")
    if md_file.exists():
        return (md_file, True)
    try:
        html_content = path.read_text(encoding="utf-8", errors="ignore")
        doc = Document(html_content)
        main_content = doc.summary()
        markdown = md(main_content)
        if markdown and markdown.strip():
            md_file.write_text(markdown, encoding="utf-8")
            print(f"✓ Converted: {path.name} -> {md_file.name}")
            if remove_orig:
                path.unlink()
            return (md_file, True)
        print(f"✗ No content extracted from {path.name}")
        return (path, False)
    except Exception as e:
        print(f"✗ Error: {e}")
        return (path, False)


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = (
        [Path(p) for p in args]
        if args
        else get_files(cwd, ext=[".html", ".htm", ".xhtml", ".xhtm"])
    )
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf3(process_file, files)
