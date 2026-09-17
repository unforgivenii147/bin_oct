#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def create_html_template(filename: str = "index.html") -> None:
    html_template = '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>Document</title>\n</head>\n<body>\n    <h1>Hello, World!</h1>\n    <!-- Your content here -->\n</body>\n</html>\n'
    try:
        Path(filename).write_text(html_template, encoding="utf-8")
        print(f"Successfully created {filename} in {Path.cwd()}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    create_html_template()
