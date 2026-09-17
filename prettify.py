#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import cssbeautifier
import yapf
from bs4 import BeautifulSoup


def beautify_html(path) -> bool:
    try:
        content = Path(path).read_text(encoding="utf-8")
        soup = BeautifulSoup(content, "html.parser")
        beautified_content = soup.prettify()
        Path(path).write_text(beautified_content, encoding="utf-8")
    except Exception as e:
        print(f"Error beautifying HTML file {path}: {e}")
        return False
    return True


def beautify_css(path) -> bool:
    try:
        content = Path(path).read_text(encoding="utf-8")
        beautified_content = cssbeautifier.beautify(content)
        Path(path).write_text(beautified_content, encoding="utf-8")
    except Exception as e:
        print(f"Error beautifying CSS file {path}: {e}")
        return False
    return True


def beautify_js(path) -> bool:
    try:
        content = Path(path).read_text(encoding="utf-8")
        beautified_content, _ = yapf.yapf_api.FormatCode(content)
        Path(path).write_text(beautified_content, encoding="utf-8")
    except Exception as e:
        print(f"Error beautifying JS file {path}: {e}")
        return False
    return True


def beautify_directory(directory: str) -> None:
    failed_files = []
    base_path = Path(directory)
    for path in base_path.rglob("*"):
        if not path.is_file():
            continue
        file = path.name
        success = False
        if file.endswith(".html"):
            print(f"Beautifying HTML: {path}")
            success = beautify_html(path)
        elif file.endswith(".css"):
            print(f"Beautifying CSS: {path}")
            success = beautify_css(path)
        elif file.endswith(".js"):
            print(f"Beautifying JS: {path}")
            success = beautify_js(path)
        else:
            continue
        if not success:
            failed_files.append(str(path))
    if failed_files:
        print("\nThe following files failed to be beautified:")
        for failed_file in failed_files:
            print(failed_file)
    else:
        print("\nAll files beautified successfully.")


if __name__ == "__main__":
    beautify_directory(".")
