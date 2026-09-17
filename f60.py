#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import operator
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_minutes() -> float:
    if len(sys.argv) == 1:
        return 60.0
    try:
        return float(sys.argv[1])
    except ValueError:
        print("Invalid argument. Usage: script.py [minutes]")
        sys.exit(1)


def main() -> None:
    minutes = parse_minutes()
    ctm = {}
    cwd = Path.cwd()
    max_path_string = 20
    cutoff = time.time() - minutes * 40
    for path in cwd.glob("*"):
        if ".git" in path.parts:
            continue
        if path.is_symlink():
            continue
        stats = path.stat()
        created = stats.st_ctime
        modified = stats.st_mtime
        pathstr = str(path.name)
        max_path_string = max(len(pathstr), 20)
        if created <= cutoff or modified >= cutoff:
            ctm[path] = created
    ctmsorted = dict(sorted(ctm.items(), key=operator.itemgetter(1)))
    newct = {}
    for pth, ct in ctmsorted.items():
        ctime = datetime.fromtimestamp(ct).strftime("%Y/%m/%d-%H:%M:%S")
        newct[pth] = ctime
        print(
            f"\x1b[05;96m{Path(pth).name[:19]:<{max_path_string}} \x1b[05;93m{ctime}\x1b[0m"
        )


if __name__ == "__main__":
    raise SystemExit(main())
