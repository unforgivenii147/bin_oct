#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_pyfiles, runcmd

CHUNK_SIZE = 1024 * 1024


def process_file(path) -> None:
    path = Path(path)
    cmd = [
        "pylint",
        f"{path!s}",
        "--persistent=n",
        "--reports=n",
        "--output-format=parseable",
        "--msg-template='{C}:{line}:{column}:{obj}:{msg}:{msg_id}'",
        str(path),
    ]
    return runcmd(cmd, show_output=True)


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            if p.is_dir():
                files.extend(get_pyfiles(p))
    else:
        files = get_pyfiles(cwd)
    for f in files:
        process_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
