#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import glob
import shutil
import sys
from pathlib import Path

from dh import unique_path

dest = Path.home() / "isaac" / "may" / "scripts"


def expand(arg: str) -> list[Path]:
    # Let the shell do its thing first; if nothing matched, try globbing ourselves.
    p = Path(arg)
    if p.exists():
        return [p]
    matches = glob.glob(arg, recursive=True)
    return [Path(m) for m in matches if Path(m).is_file()]


def main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: {Path(sys.argv[0]).name} FILE [FILE ...]", file=sys.stderr)
        raise SystemExit(1)

    files: list[Path] = []
    for arg in sys.argv[1:]:
        found = expand(arg)
        if not found:
            print(f"no matches: {arg}", file=sys.stderr)
            continue
        files.extend(found)

    for fn in files:
        dest_path = dest / fn.name
        if dest_path.exists():
            dest_path = unique_path(dest_path)
        shutil.move(str(fn), str(dest_path))
        print(f"{fn.name} --> {dest_path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
