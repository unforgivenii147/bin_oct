#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def process_file(path: Path) -> None:
    path = Path(path)
    con = path.read_text()
    nl = [(line + "\n\n\n\n") for line in con.splitlines()]
    newconn = "\n".join(nl)
    path.write_text(newconn)


if __name__ == "__main__":
    fn = Path(sys.argv[1])
    process_file(fn)
