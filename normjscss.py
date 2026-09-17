#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

DIRS = [Path()]
ver_pattern = re.compile(r"\?[a-zA-Z0-9_-]+=[^\"\'\s>]+", re.IGNORECASE)


def strip_ver_suffix(filename: str) -> str:
    return ver_pattern.sub("", filename)


def rename_files(base: Path) -> None:
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        new_name = strip_ver_suffix(path.name)
        if new_name != path.name:
            new_path = path.with_name(new_name)
            print(f"Renaming: {path} -> {new_path}")
            try:
                path.rename(new_path)
            except FileExistsError:
                print(f"  Skipped (target exists): {new_path}")


def update_html_files(base: Path) -> None:
    for html_file in base.rglob("*.html"):
        text = html_file.read_text(encoding="utf-8", errors="ignore")
        new_text = strip_ver_suffix(text)
        if new_text != text:
            print(f"Updating HTML: {html_file}")
            html_file.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    for d in DIRS:
        rename_files(d)
        update_html_files(d)
    print("\nDone. All ?ver=... removed from filenames and HTML files.")
