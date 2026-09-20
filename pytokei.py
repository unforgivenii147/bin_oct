#!/data/data/com.termux/files/home/.local/bin/python
"""
pytokei_merged.py — count lines of code, comments, and blanks by language.

Merged from:
  - pytokei.py
  - pytokei2.py

Original mapping
----------------
pytokei.py   -> python pytokei_merged.py [root]
pytokei2.py  -> python pytokei_merged.py [root] --no-report

Both scripts count lines of code, comment lines, and blank lines for a set of
languages. pytokei.py prints a final report; pytokei2.py computes the same
statistics but does not print the final report (it still prints binary-file
warnings). The --no-report flag reproduces pytokei2.py's output behavior.

Usage examples
--------------
  python pytokei_merged.py
  python pytokei_merged.py src/
  python pytokei_merged.py src/ --no-report
  python pytokei_merged.py . --exclude .venv --exclude node_modules

Dependencies
------------
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Configuration constants (originally hardcoded in both scripts)
# ---------------------------------------------------------------------------

LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
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

COMMENT_PATTERNS: dict[str, str] = {
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

SHEBANG_PATTERNS: dict[str, list[str]] = {
    "python": [
        "#!/usr/bin/env python",
        "#!/usr/bin/python3",
        "#!/bin/python3",
    ],
    "bash": ["#!/bin/bash"],
    "ruby": ["#!/usr/bin/ruby", "#!/bin/ruby"],
    "perl": ["#!/usr/bin/perl"],
    "node": ["#!/usr/bin/node", "#!/bin/node"],
    "sh": ["#!/bin/sh"],
}

DEFAULT_EXCLUDES: list[str] = [".git"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary (contains NUL bytes)."""
    try:
        with path.open("rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except OSError:
        return False


def _contains_exclude(path: Path, excludes: set[str]) -> bool:
    """Return True if any exclude substring appears in the path string."""
    s = str(path)
    return any(ex in s for ex in excludes)


def detect_shebang(path: Path, excludes: set[str]) -> str | None:
    """Detect language from a shebang line for extensionless files."""
    if is_binary(path):
        print(f"{path} is binary")
        return None
    if _contains_exclude(path, excludes):
        return None
    try:
        with path.open(encoding="utf-8") as f:
            first = f.readline().strip()
        for lang, shebangs in SHEBANG_PATTERNS.items():
            for shebang in shebangs:
                if first.startswith(shebang):
                    return lang
    except Exception as exc:
        print(f"Error reading file {path}:{exc}")
    return None


def count_file(
    path: Path,
    language: str,
    excludes: set[str],
) -> tuple[int, int, int]:
    """Count (code, comments, blank) lines in a file."""
    if _contains_exclude(path, excludes):
        return (0, 0, 0)
    if is_binary(path):
        print(f"{path} is binary")
        return (0, 0, 0)

    code = comments = blank = 0
    pattern = COMMENT_PATTERNS.get(language, "")

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    blank += 1
                elif re.match(pattern, line):
                    comments += 1
                else:
                    code += 1
    except Exception as exc:
        print(f"Error reading file {path}:{exc}")
        return (0, 0, 0)

    return (code, comments, blank)


def _add(
    stats: dict[str, Any],
    language: str,
    code: int,
    comments: int,
    blank: int,
) -> None:
    """Accumulate counts into the stats dictionary."""
    stats["languages"][language]["code"] += code
    stats["languages"][language]["comments"] += comments
    stats["languages"][language]["blank"] += blank
    stats["total"]["code"] += code
    stats["total"]["comments"] += comments
    stats["total"]["blank"] += blank


def analyze(root: Path, excludes: set[str]) -> dict[str, Any]:
    """Walk *root* and return code/comment/blank statistics."""
    stats: dict[str, Any] = {
        "total": {"code": 0, "comments": 0, "blank": 0},
        "languages": {
            lang: {"code": 0, "comments": 0, "blank": 0} for lang in LANGUAGE_EXTENSIONS
        },
    }

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        suffix = path.suffix.lower()

        # Extensionless files: try shebang detection.
        if not suffix:
            lang = detect_shebang(path, excludes)
            if lang:
                c, m, b = count_file(path, lang, excludes)
                _add(stats, lang, c, m, b)
                continue

        # Extension-based detection.
        for lang, exts in LANGUAGE_EXTENSIONS.items():
            if suffix in exts:
                c, m, b = count_file(path, lang, excludes)
                _add(stats, lang, c, m, b)
                break

    return stats


def print_report(stats: dict[str, Any]) -> None:
    """Print statistics in the format used by pytokei.py."""
    print(f"Total lines of code:{stats['total']['code']}")
    print(f"Total comment lines:{stats['total']['comments']}")
    print(f"Total blank lines:{stats['total']['blank']}\n")
    print("Language-based statistics:")

    for lang, counts in stats["languages"].items():
        if counts["code"] > 0:
            print(f"\n{lang.capitalize()}:")
            print(f"  Code lines:{counts['code']}")
            print(f"  Comment lines:{counts['comments']}")
            print(f"  Blank lines:{counts['blank']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pytokei_merged.py",
        description="Count lines of code, comments, and blanks by language.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to analyze. Default: current directory.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Suppress final statistics report (pytokei2.py behavior).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=DEFAULT_EXCLUDES,
        help="Substrings to exclude from paths. Can be repeated. Default: .git",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory")
        return 1

    excludes = set(args.exclude)
    stats = analyze(root, excludes)

    if not args.no_report:
        print_report(stats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
