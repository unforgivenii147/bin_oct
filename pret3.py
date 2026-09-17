#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import jsbeautifier


def beautify_file(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        beautified_content = jsbeautifier.beautify(content)
    elif path.suffix == ".css":
        beautified_content = jsbeautifier.css(content)
    elif path.suffix == ".html":
        beautified_content = jsbeautifier.html(content)
    else:
        return
    path.write_text(beautified_content, encoding="utf-8")


def beautify_directory(directory: str) -> None:
    base_path = Path(directory)
    for path in base_path.rglob("*"):
        if path.is_file() and path.suffix in (".js", ".css", ".html"):
            print(f"Beautifying: {path}")
            beautify_file(path)


if __name__ == "__main__":
    beautify_directory(".")
