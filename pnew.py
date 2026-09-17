#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1])
    template = """#!/data/data/com.termux/files/usr/bin/python
from pathlib import Path
import sys
from dh import get_files
from pbar import Pbar
def process_file(path) -> None:
    pass
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
    with Pbar("") as pbar:
        for f in pbar.wrap(files):
            process_file(f)
if __name__ == "__main__":
    raise SystemExit(main())
"""
    path.write_text(template, encoding="utf-8")
    print(f"{path.name} created.")


if __name__ == "__main__":
    raise SystemExit(main())
