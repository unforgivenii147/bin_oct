#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import datetime
from pathlib import Path

from dh import cprint, fsz, gsz

if __name__ == "__main__":
    cwd = Path.cwd()
    for path in sorted(cwd.glob("*"), key=lambda e: e.stat().st_mtime):
        mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")
        if path.is_symlink():
            sz = " symlink "
        elif path.is_file() or path.is_dir():
            sz = str(fsz(gsz(path)))
            match len(sz):
                case 3:
                    sz = "      " + sz
                case 4:
                    sz = "     " + sz
                case 5:
                    sz = "    " + sz
                case 6:
                    sz = "   " + sz
                case 7:
                    sz = "  " + sz
                case 8:
                    sz = " " + sz
        cprint(f"{path.name[:24]:25}", "blue", end=" ")
        cprint(f"{sz}", "cyan", end=" ")
        cprint(f"{mtime}", "yellow")
