#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3

skl = """SKIP_DIRS: frozenset = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})"""


def process_file(path) -> None:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    nl = []
    for line in lines:
        if line.strip() != skl:
            nl.append(line)
    new_content = "".join(nl)
    path.write_text(new_content, encoding="utf-8")


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            if p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
