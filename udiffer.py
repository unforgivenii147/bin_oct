#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import difflib
import sys


def _read_lines(filename):
    try:
        with open(filename) as f:
            return f.readlines()
    except UnicodeDecodeError:
        with open(filename, encoding="utf_16") as f:
            return f.readlines()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("first", metavar="FILE")
    parser.add_argument("second", metavar="FILE")
    config = parser.parse_args()
    first = _read_lines(config.first)
    second = _read_lines(config.second)
    diffs = list(
        difflib.unified_diff(first, second, fromfile=config.first, tofile=config.second)
    )
    if diffs:
        sys.stdout.writelines(diffs)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
