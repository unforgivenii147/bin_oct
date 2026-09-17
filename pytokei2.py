#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

from dh import is_binary


def count_lines_of_code(path: Path, lang) -> tuple[int, int, int]:
    if ".git" in str(path):
        return (0, 0, 0)
    if is_binary(str(path)):
        print(f"{path} is binary")
        return (0, 0, 0)
    with path.open(encoding="utf-8") as file:
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
    return (code_lines, comment_lines, blank_lines)


def scan_directory(directory: str = "."):
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
                code, comments, blanks = count_lines_of_code(path, lang)
                stats["languages"][lang]["code"] += code
                stats["languages"][lang]["comments"] += comments
                stats["languages"][lang]["blank"] += blanks
                stats["total"]["code"] += code
                stats["total"]["comments"] += comments
                stats["total"]["blank"] += blanks
                continue
        for lang, extensions in LANG_EXTENSIONS.items():
            if file_extension in extensions:
                code, comments, blanks = count_lines_of_code(path, lang)
                stats["languages"][lang]["code"] += code
                stats["languages"][lang]["comments"] += comments
                stats["languages"][lang]["blank"] += blanks
                stats["total"]["code"] += code
                stats["total"]["comments"] += comments
                stats["total"]["blank"] += blanks
                break
    return stats


def display_stats(stats) -> None:
    for lang_stats in stats["languages"].values():
        lang_stats["code"] > 0


if __name__ == "__main__":
    stats = scan_directory()
    display_stats(stats)
