#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import datetime
import os
import shutil
import stat
import sys
from pathlib import Path

REVERSE = "-r" in sys.argv


def fsz(sz: int) -> str:
    """Format bytes into a compact human-readable string."""
    sz = abs(int(sz))
    if sz < 1024:
        return f"{sz} B"
    units = ("K", "M", "G", "T", "P")
    i = -1
    v = float(sz)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    # Show one decimal if it fits nicely, otherwise round
    if v < 10:
        s = f"{v:.1f}"
        s = s.removesuffix(".0")
    else:
        s = f"{int(v)}"
    return f"{s} {units[i]}B"


def gsz(path: str | Path) -> int:
    """
    Recursively compute total size of a file or directory.
    - Counts real files only.
    - Does not follow symlinks.
    - Handles hardlinks (counts each link once per unique inode).
    - Robust against permission/IO errors.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return 0

    mode = st.st_mode
    if stat.S_ISLNK(mode):
        # Count symlink's own size (the link target string), not the target
        return st.st_size
    if stat.S_ISREG(mode):
        return st.st_size
    if not stat.S_ISDIR(mode):
        return 0

    total = 0
    seen: set[tuple[int, int]] = set()
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        est = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    emode = est.st_mode
                    if stat.S_ISLNK(emode):
                        total += est.st_size
                    elif stat.S_ISREG(emode):
                        key = (est.st_dev, est.st_ino)
                        if key in seen:
                            continue
                        seen.add(key)
                        total += est.st_size
                    elif stat.S_ISDIR(emode):
                        stack.append(entry.path)
        except OSError:
            continue
    return total


def fmt_time(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def visible_len(s: str) -> int:
    """Length of a string ignoring ANSI escape sequences."""
    n = 0
    i = 0
    L = len(s)
    while i < L:
        c = s[i]
        if c == "\x1b":
            # skip until 'm'
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        n += 1
        i += 1
    return n


def truncate(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width == 1:
        return "…"
    return s[: width - 1] + "…"


def main() -> None:
    cwd = Path.cwd()

    term_w = shutil.get_terminal_size(fallback=(80, 24)).columns

    dirz: list[tuple[Path, int, float]] = []
    otherz: list[tuple[Path, int, float]] = []

    entries = [p for p in cwd.iterdir()]

    for entry in entries:
        p = Path(entry)
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        try:
            if entry.is_dir():
                size = gsz(p)
                dirz.append((p, size, st.st_ctime))
            else:
                if stat.S_ISLNK(st.st_mode):
                    size = st.st_size  # symlink string length
                else:
                    size = st.st_size
                otherz.append((p, size, st.st_ctime))
        except OSError:
            continue

    # Sort files by size; dirs alphabetically (as original did)
    otherz.sort(key=lambda t: t[1], reverse=REVERSE)
    dirz.sort(key=lambda t: t[0].name.lower(), reverse=REVERSE)

    # Layout: NAME | SIZE | TIME
    # Reserve fixed width for size (8) and time (5) plus 2 spaces between cols
    SIZE_W = 8
    TIME_W = 5
    fixed = SIZE_W + TIME_W + 4  # spaces between/after
    name_w = max(10, term_w - fixed)

    # RGB (255, 127, 80) → ANSI 256-color approximation: 209
    # If your terminal supports truecolor, use: \x1b[38;2;255;127;80m
    TIME_COLOR = "\x1b[38;2;255;127;80m"

    def emit(name: str, size: int, ctime: float, name_color: str) -> None:
        size_str = fsz(size)
        # Right-align size within SIZE_W
        size_col = size_str.rjust(SIZE_W)
        t = fmt_time(ctime)
        name_disp = truncate(name, name_w)
        # Pad name to name_w using visible length
        pad = name_w - visible_len(name_disp)
        pad = max(pad, 0)
        print(
            f"\x1b[05;{name_color}m{name_disp}\x1b[0m"
            f"{' ' * pad}"
            f" \x1b[05;96m{size_col}\x1b[0m"
            f" {TIME_COLOR}{t}\x1b[0m"
        )

    for p, sz, ct in otherz:
        name = p.name
        # Executable check
        try:
            mode = p.stat(follow_symlinks=False).st_mode
        except OSError:
            mode = 0
        if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            # Executable → green
            emit(name, sz, ct, "92")
        else:
            # Non-executable file → bold blue
            emit(name, sz, ct, "96")

    for p, sz, ct in dirz:
        emit(p.name, sz, ct, "94")


if __name__ == "__main__":
    main()
