#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def convert_codepen_html(html_content, title="Document", charset="UTF-8"):
    full_html = f'<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="{
        charset
    }">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>{
        title
    }</title>\n    <link rel="stylesheet" href="style.css">\n</head>\n<body>\n{
        html_content
    }\n    <script src="script.js"></script>\n</body>\n</html>\n'
    return full_html


def process_file(input_file, output_file=None, title=None):
    try:
        with open(input_file, encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found.")
        return False
    except Exception as e:
        print(f"Error reading file: {e}")
        return False
    if title is None:
        title = Path(input_file).stem.replace("-", " ").title()
    full_html = convert_codepen_html(html_content, title)
    if output_file is None:
        output_file = input_file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(full_html)
        print(f"✓ Successfully converted: {input_file}")
        print(f"✓ Saved to: {output_file}")
        return True
    except Exception as e:
        print(f"Error writing file: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python codepen_converter.py <input_file> [output_file] [--title 'Page Title']"
        )
        print("\nExample:")
        print("  python codepen_converter.py index.html")
        print("  python codepen_converter.py codepen.html output.html")
        print("  python codepen_converter.py codepen.html --title 'My Project'")
        sys.exit(1)
    input_file = sys.argv[1]
    output_file = None
    title = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--title" and i + 1 < len(sys.argv):
            title = sys.argv[i + 1]
            i += 2
        else:
            output_file = sys.argv[i]
            i += 1
    success = process_file(input_file, output_file, title)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    raise SystemExit(main())
