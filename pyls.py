#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import datetime
import grp
import pwd
import stat
import sys
from argparse import Namespace
from pathlib import Path

from dh import fsz

COLORS = {"dir": "\x1b[34m", "link": "\x1b[36m", "exec": "\x1b[32m", "reset": "\x1b[0m"}


def use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def colorize(name, st, enabled):
    if not enabled:
        return name
    if stat.S_ISDIR(st.st_mode):
        return f"{COLORS['dir']}{name}{COLORS['reset']}"
    if stat.S_ISLNK(st.st_mode):
        return f"{COLORS['link']}{name}{COLORS['reset']}"
    if st.st_mode & stat.S_IXUSR:
        return f"{COLORS['exec']}{name}{COLORS['reset']}"
    return name


def indicator(path, st):
    if stat.S_ISDIR(st.st_mode):
        return "/"
    if stat.S_ISLNK(st.st_mode):
        return "@"
    if st.st_mode & stat.S_IXUSR:
        return "*"
    return ""


def format_time(ts, full) -> str:
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S" if full else "%b %d %H:%M")


def format_entry(entry, args: Namespace, color_enabled: bool) -> str:
    try:
        st = entry.stat(follow_symlinks=args.L)
    except FileNotFoundError:
        return ""
    name = entry.name
    name = colorize(name, st, color_enabled)
    if args.p and entry.is_dir():
        name += "/"
    if args.F:
        name += indicator(entry, st)
    inode = f"{st.st_ino} " if args.i else ""
    blocks = f"{st.st_blocks} " if args.s else ""
    if not args.l:
        return f"{inode}{blocks}{name}"
    perms = stat.filemode(st.st_mode)
    nlink = st.st_nlink
    uid = st.st_uid if args.n else pwd.getpwuid(st.st_uid).pw_name
    gid = st.st_gid if args.n else grp.getgrgid(st.st_gid).gr_name
    size = fsz(st.st_size) if args.h else st.st_size
    ts = st.st_ctime if args.lc else st.st_atime if args.lu else st.st_mtime
    time_str = format_time(ts, args.full_time)
    return f"{inode} {blocks} {perms}  {nlink}  {uid}  {gid}  {size: >6}  {time_str}  {name} "


def scan_dir(path: Path, args: Namespace):
    try:
        entries = list(path.iterdir())
    except PermissionError:
        print(f"ls: cannot open directory '{path}'", file=sys.stderr)
        return []
    if not args.a:
        if args.A:
            entries = [
                e
                for e in entries
                if e.name not in {".", ".."} and not e.name.startswith(".")
            ]
        else:
            entries = [e for e in entries if not e.name.startswith(".")]

    def key(p):
        try:
            st = p.stat(follow_symlinks=args.L)
        except FileNotFoundError:
            return 0
        if args.S:
            return -st.st_size
        if args.t:
            return -st.st_mtime
        if args.tc:
            return -st.st_ctime
        if args.tu:
            return -st.st_atime
        if args.X:
            return p.suffix
        return p.name

    entries.sort(key=key, reverse=args.r)
    if args.group_directories_first:
        entries.sort(key=lambda e: not e.is_dir())
    return entries


def print_columns(items: list[str], width, by_row) -> None:
    if not items:
        return
    max_len = max(len(i) for i in items) + 2
    cols = max(1, width // max_len)
    rows = (len(items) + cols - 1) // cols
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c if by_row else c * rows + r
            if idx < len(items):
                print(items[idx].ljust(max_len), end="")
        print()


def main() -> None:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-1", dest="one", action="store_true")
    p.add_argument("-a", action="store_true")
    p.add_argument("-A", action="store_true")
    p.add_argument("-x", action="store_true")
    p.add_argument("-d", action="store_true")
    p.add_argument("-L", action="store_true")
    p.add_argument("-H", action="store_true")
    p.add_argument("-R", action="store_true")
    p.add_argument("-p", action="store_true")
    p.add_argument("-F", action="store_true")
    p.add_argument("-l", action="store_true")
    p.add_argument("-i", action="store_true")
    p.add_argument("-n", action="store_true")
    p.add_argument("-s", action="store_true")
    p.add_argument("-h", action="store_true")
    p.add_argument("-lc", action="store_true")
    p.add_argument("-lu", action="store_true")
    p.add_argument("--full-time", action="store_true")
    p.add_argument("-S", action="store_true")
    p.add_argument("-X", action="store_true")
    p.add_argument("-v", action="store_true")
    p.add_argument("-t", action="store_true")
    p.add_argument("-tc", action="store_true")
    p.add_argument("-tu", action="store_true")
    p.add_argument("-r", action="store_true")
    p.add_argument("-w", type=int, default=80)
    p.add_argument("--group-directories-first", action="store_true")
    p.add_argument("--color", nargs="?", const="auto", default="auto")
    p.add_argument("paths", nargs="*", default=["."])
    args = p.parse_args()
    color_enabled = use_color(args.color)
    for path in args.paths:
        path = Path(path)
        if args.d or not path.is_dir():
            print(format_entry(path, args, color_enabled))
            continue
        entries = scan_dir(path, args)
        formatted = [format_entry(e, args, color_enabled) for e in entries]
        if args.l or args._get_kwargs():
            for f in formatted:
                print(f)
        elif args._1:
            print("\n".join(formatted))
        else:
            print_columns(formatted, args.w, args.x)
        if args.R:
            for e in entries:
                if e.is_dir() and not e.is_symlink():
                    print(f"\n{e}:")
                    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
