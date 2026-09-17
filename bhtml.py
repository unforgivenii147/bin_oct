#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import subprocess
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python beautify-html.py <filename>")
        print("Example: python beautify-html.py index.html")
        sys.exit(1)
    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            original_content = f.read()
        process = subprocess.Popen(
            ["html-beautify"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        beautified, error = process.communicate(input=original_content)
        if process.returncode != 0:
            print(f"Error running html-beautify: {error}")
            sys.exit(1)
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(beautified)
        print(f"✅ Successfully beautified: {input_file}")
    except FileNotFoundError:
        print("Error: 'html-beautify' command not found. Please install js-beautify:")
        print("  npm install -g js-beautify")
        sys.exit(1)
    except Exception as e:
        print(f"Error beautifying file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
