#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import sys
import unicodedata
from pathlib import Path

import astor
from dh import get_files, is_binary

BACKUP = False


def process_file(path) -> None:
    path = Path(path)
    if is_binary(path):
        return
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if BACKUP:
            backup_file = path.with_suffix(path.suffix + ".bak")
            backup_file.write_text(content, encoding="utf-8")
        new_content = content
        if path.suffix == ".py":
            try:
                tree = ast.parse(content)
                new_content = astor.to_source(tree)
                path.write_text(new_content, encoding="utf-8")
                print(f"\x1b[0m[ \x1b[6;96m✓\x1b[0m ] {path.name} ")
                return
            except:
                print(f"\x1b[0m[ \x1b[6;96m✘\x1b[0m ] {path.name} ")
                return
        else:
            new_content = unicodedata.normalize("NFD", content)
            path.write_text(new_content, encoding="utf-8")
    except:
        return


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    sys.argv[2] if len(sys.argv) > 2 else False
    files = [Path(arg) for arg in args] if args else get_files(cwd)
    for path in files:
        process_file(path)


if __name__ == "__main__":
    raise SystemExit(main())
