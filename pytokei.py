#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

from dh import is_binary

LANG_EXTENSIONS = {
    "python": [".py", ".pyi"],
    "javascript": [".js"],
    "java": [".java"],
    "c": [".c"],
    "cpp": [".cpp", ".h"],
    "html": [".html"],
    "css": [".css"],
    "ruby": [".rb"],
    "php": [".php"],
    "bash": [".sh", ".bash"],
}
COMMENT_PATTERNS = {
    "python": r"^\s*#",
    "javascript": r"^\s*//",
    "java": r"^\s*//",
    "c": r"^\s*//",
    "cpp": r"^\s*//",
    "html": r"^\s*<!--",
    "css": r"^\s*/\*",
    "ruby": r"^\s*#",
    "php": r"^\s*//",
}
SHEBANG_LANGUAGES = {
    "python": ["#!/usr/bin/env python", "#!/usr/bin/python3", "#!/bin/python3"],
    "bash": ["#!/bin/bash"],
    "ruby": ["#!/usr/bin/ruby", "#!/bin/ruby"],
    "perl": ["#!/usr/bin/perl"],
    "node": ["#!/usr/bin/node", "#!/bin/node"],
    "sh": ["#!/bin/sh"],
}


def get_language_from_shebang(path: str) -> str | None:
    if is_binary(path):
        print(f"{path} is binary")
        return None
    if ".git" in str(path):
        return None
    try:
        with Path(path).open(encoding="utf-8") as file:
            first_line = file.readline().strip()
            for lang, shebangs in SHEBANG_LANGUAGES.items():
                for shebang in shebangs:
                    if first_line.startswith(shebang):
                        return lang
    except Exception as e:
        print(f"Error reading file {path}: {e}")
    return None


def count_lines_of_code(path: str, lang: str) -> tuple[int, int, int]:
    if ".git" in str(path):
        return 0, 0, 0
    if is_binary(path):
        print(f"{path} is binary")
        return 0, 0, 0
    with Path(path).open(encoding="utf-8") as file:
        code_lines = 0
        comment_lines = 0
        blank_lines = 0
        for line in file:
            if not line.strip():
                blank_lines += 1
            elif re.match(COMMENT_PATTERNS.get(lang, ""), line):
                comment_lines += 1
            else:
                code_lines += 1
    return code_lines, comment_lines, blank_lines


def scan_directory(
    directory: str = ".",
) -> dict[str, dict[str, dict[str, int]] | dict[str, int]]:
    stats = {
        "total": {"code": 0, "comments": 0, "blank": 0},
        "languages": {
            lang: {"code": 0, "comments": 0, "blank": 0} for lang in LANG_EXTENSIONS
        },
    }
    base_path = Path(directory)
    for path in base_path.rglob("*"):
        if not path.is_file():
            continue
        file_extension = path.suffix.lower()
        if not file_extension:
            lang = get_language_from_shebang(str(path))
            if lang:
                code, comments, blanks = count_lines_of_code(str(path), lang)
                stats["languages"][lang]["code"] += code
                stats["languages"][lang]["comments"] += comments
                stats["languages"][lang]["blank"] += blanks
                stats["total"]["code"] += code
                stats["total"]["comments"] += comments
                stats["total"]["blank"] += blanks
                continue
        for lang, extensions in LANG_EXTENSIONS.items():
            if file_extension in extensions:
                code, comments, blanks = count_lines_of_code(str(path), lang)
                stats["languages"][lang]["code"] += code
                stats["languages"][lang]["comments"] += comments
                stats["languages"][lang]["blank"] += blanks
                stats["total"]["code"] += code
                stats["total"]["comments"] += comments
                stats["total"]["blank"] += blanks
                break
    return stats


def display_stats(stats: dict[str, dict[str, dict[str, int]] | dict[str, int]]) -> None:
    print(f"Total lines of code: {stats['total']['code']}")
    print(f"Total comment lines: {stats['total']['comments']}")
    print(f"Total blank lines: {stats['total']['blank']}\n")
    print("Language-based statistics:")
    for lang, lang_stats in stats["languages"].items():
        if lang_stats["code"] > 0:
            print(f"\n{lang.capitalize()}:")
            print(f"  Code lines: {lang_stats['code']}")
            print(f"  Comment lines: {lang_stats['comments']}")
            print(f"  Blank lines: {lang_stats['blank']}")


if __name__ == "__main__":
    stats = scan_directory()
    display_stats(stats)
