#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import re
import sys
from multiprocessing import get_context
from pathlib import Path

from dh import fsz, get_nobinary, gsz, is_binary


def process_file(path: Path) -> None:
    Path(path)
    if is_binary(path):
        return
    before = gsz(path)
    path.read_text(encoding="utf-8")
    orig = re.sub("#.*", "")
    orig = re.sub("\\n\\n*", "\n")
    if path.suffix == ".py":
        try:
            ast.parse(orig)
            path.write_text(orig, encoding="utf-8")
            after = gsz(path)
            print(f"{path.name} ", end=" ")
            print(fsz(before - after))
        except:
            return
    else:
        path.write_text(orig, encoding="utf-8")
        after = gsz(path)
        print(f"{path.name} ", end=" ")
        print(fsz(before - after))


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_nobinary(cwd)
    p = get_context("spawn").Pool(8)
    for f in files:
        p.apply_async(process_file, (f,))
    p.close()
    p.join()
    diff_size = before - gsz(cwd)
    print(f"space change: {fsz(diff_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
