#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys

EXTENSION_COMMENTS = {
    ".py": "#",
    ".sh": "#",
    ".yaml": "#",
    ".yml": "#",
    ".rb": "#",
    ".js": "//",
    ".ts": "//",
    ".cpp": "//",
    ".c": "//",
    ".java": "//",
    ".go": "//",
    ".html": "<!--",
    ".css": "/*",
}


def main():
    if len(sys.argv) < 4:
        print(
            "Error: Missing arguments.\nUsage: python comment_range.py <filename> <start_line> <end_line>"
        )
        sys.exit(1)
    path = sys.argv[1]
    try:
        start_line = int(sys.argv[2])
        end_line = int(sys.argv[3])
    except ValueError:
        print("Error: Start and end lines must be valid integers.")
        sys.exit(1)
    if start_line < 1 or end_line < start_line:
        print(
            "Error: Line numbers must start from 1, and end line must be >= start line."
        )
        sys.exit(1)
    if not os.path.exists(path):
        print(f"Error: The file '{path}' does not exist.")
        sys.exit(1)
    _, ext = os.path.splitext(path.lower())
    comment_char = EXTENSION_COMMENTS.get(ext, "#")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    total_lines = len(lines)
    if start_line > total_lines:
        print(
            f"Error: Start line ({start_line}) exceeds file length ({total_lines} lines)."
        )
        sys.exit(1)
    actual_end = min(end_line, total_lines)
    for i in range(start_line - 1, actual_end):
        if not lines[i].strip().startswith(comment_char):
            lines[i] = f"{comment_char} {lines[i]}"
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(
        f"Success: Commented out lines {start_line} to {actual_end} in '{path}' using '{comment_char}'."
    )


if __name__ == "__main__":
    raise SystemExit(main())
