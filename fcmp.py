#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from filecmp import dircmp
from pathlib import Path
from pprint import pprint

if __name__ == "__main__":
    dir1 = Path.cwd()
    dir2 = Path(sys.argv[1])
    c = dircmp(dir1, dir2)
    pprint(c.report_full_closure())
