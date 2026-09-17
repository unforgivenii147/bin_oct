#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import datetime
import grp
import json
import pwd
import shutil
import stat
import subprocess
from argparse import Namespace
from os import getenv
from pathlib import Path

from dh import fsz


def colorize(text: str, mode: int, link_target: str | None = None) -> str:
    if stat.S_ISDIR(mode):
        return f"\x1b[34;1m{text}\x1b[0m"
    if stat.S_ISLNK(mode):
        return f"\x1b[36m{text}\x1b[0m"
    if mode & stat.S_IXUSR:
        return f"\x1b[32m{text}\x1b[0m"
    return text


def detect_icon(name: str, mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "📁"
    if stat.S_ISLNK(mode):
        return "🔗"
    ext = name.lower().split(".")[-1]
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "🖼️"
    if ext in {"py", "sh"}:
        return "🐍"
    if ext in {"zip", "tar", "gz", "bz2", "xz"}:
        return "📦"
    return "📄"


def get_git_status_for_dir(path: str) -> dict[str, dict[str, str]]:
    try:
        p = subprocess.run(
            ["git", "-C", path, "status", "--porcelain=v2", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            check=False,
        )
    except FileNotFoundError:
        return {}
    out = p.stdout
    result = {}
    records = out.split(b"\x00")
    for rec in records:
        if not rec.startswith(b"1 "):
            continue
        parts = rec.split(b" ")
        if len(parts) < 8:
            continue
        xy = parts[1].decode("utf-8")
        x, y = xy[0], xy[1]
        filename = parts[-1].decode("utf-8", errors="ignore")
        result[filename] = {"index": x, "work": y, "raw": xy}
    return result


class Entry:
    def __init__(
        self, path: str, name: str, stat_obj, link_target=None, git=None
    ) -> None:
        self.path = path
        self.name = name
        self.stat = stat_obj
        self.link_target = link_target
        self.git = git


def mode_to_string(mode: int) -> str:
    chars = []
    chars.append("d" if stat.S_ISDIR(mode) else "l" if stat.S_ISLNK(mode) else "-")
    perms = [
        (stat.S_IRUSR, "r"),
        (stat.S_IWUSR, "w"),
        (stat.S_IXUSR, "x"),
        (stat.S_IRGRP, "r"),
        (stat.S_IWGRP, "w"),
        (stat.S_IXGRP, "x"),
        (stat.S_IROTH, "r"),
        (stat.S_IWOTH, "w"),
        (stat.S_IXOTH, "x"),
    ]
    for bit, ch in perms:
        chars.append(ch if mode & bit else "-")
    return "".join(chars)


def output_long(entries: list[Entry], icons=False, colors=True, human=True) -> None:
    for e in entries:
        st = e.stat
        mode_s = mode_to_string(st.st_mode)
        nlink = st.st_nlink
        user = pwd.getpwuid(st.st_uid).pw_name
        group = grp.getgrgid(st.st_gid).gr_name
        size = fsz(st.st_size) if human else str(st.st_size)
        mtime = datetime.datetime.fromtimestamp(st.st_mtime)
        tstr = mtime.strftime("%Y-%m-%d %H:%M")
        name = e.name
        if icons:
            name = f"{detect_icon(e.name, st.st_mode)} {name}"
        if colors:
            name = colorize(name, st.st_mode, e.link_target)
        gitmark = ""
        if e.git:
            gitmark = f" {e.git['raw']}"
        print(f"{mode_s} {nlink:2} {user:8} {group:8} {size:>6} {tstr} {name}{gitmark}")


def output_columns(entries: list[Entry], icons=False, colors=True, width=None) -> None:
    if width is None:
        env_cols = getenv("COLUMNS")
        if env_cols and env_cols.isdigit():
            width = int(env_cols)
        else:
            try:
                width = shutil.get_terminal_size().columns
            except Exception:
                width = 48
    width = max(20, width)
    cols = 2
    col_width = width // cols

    def real_len(s: str) -> int:
        import re

        return len(re.sub(r"\x1b\[[0-9;]*m", "", s))

    def truncate(text: str, max_len: int) -> str:
        if real_len(text) <= max_len:
            return text
        import regex as re

        plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
        return plain[: max_len - 1] + "…"

    rendered = []
    for e in entries:
        txt = e.name
        if icons:
            txt = f"{detect_icon(e.name, e.stat.st_mode)} {txt}"
        if colors:
            txt = colorize(txt, e.stat.st_mode, e.link_target)
        txt = truncate(txt, col_width - 1)
        rendered.append(txt)
    for i in range(0, len(rendered), cols):
        row = rendered[i : i + cols]
        padded = [(r + " " * (col_width - real_len(r))) for r in row]
        print("".join(padded))


def print_tree(base: str | Path, prefix: str = "", icons=False, colors=True) -> None:
    base_path = Path(base)
    try:
        entries = sorted(base_path.iterdir(), key=lambda e: e.name)
    except PermissionError:
        print(prefix + " [permission denied]")
        return
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        try:
            st = entry.lstat()
        except FileNotFoundError:
            continue
        txt = entry.name
        if icons:
            txt = f"{detect_icon(entry.name, st.st_mode)} {txt}"
        if colors:
            txt = colorize(txt, st.st_mode)
        print(prefix + connector + txt)
        if stat.S_ISDIR(st.st_mode):
            new_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(entry, new_prefix, icons, colors)


def list_recursive(base: str | Path, args: Namespace, depth=0) -> None:
    base_path = Path(base)
    if depth > 0:
        print(f"\n{base}:")
    try:
        entries_iter = list(base_path.iterdir())
    except PermissionError:
        print("Permission denied:", base)
        return
    entries_iter = sorted(entries_iter, key=lambda e: e.name)
    gitmap = get_git_status_for_dir(str(base_path)) if args.git else {}
    entries = []
    for entry in entries_iter:
        n = entry.name
        if not args.all and n.startswith("."):
            continue
        try:
            st = entry.lstat()
        except FileNotFoundError:
            continue
        link_t = None
        if stat.S_ISLNK(st.st_mode):
            try:
                link_t = entry.readlink()
            except OSError:
                link_t = None
        git = gitmap.get(n)
        entries.append(Entry(str(entry), n, st, link_t, git))
    print_entries(entries, args)
    for e in entries:
        if stat.S_ISDIR(e.stat.st_mode):
            list_recursive(e.path, args, depth + 1)


def print_entries(entries: list[Entry], args: Namespace) -> None:
    if args.json:
        out = [
            {
                "name": e.name,
                "size": e.stat.st_size,
                "mode": mode_to_string(e.stat.st_mode),
                "mtime": e.stat.st_mtime,
                "git": e.git,
                "type": "dir"
                if stat.S_ISDIR(e.stat.st_mode)
                else "link"
                if stat.S_ISLNK(e.stat.st_mode)
                else "file",
            }
            for e in entries
        ]
        print(json.dumps(out, indent=2))
        return
    if args.long:
        output_long(entries, icons=args.icons, colors=not args.no_color)
        return
    output_columns(entries, icons=args.icons, colors=not args.no_color)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="*", default=["."], help="Files or directories")
    p.add_argument("-l", "--long", action="store_true")
    p.add_argument("-a", "--all", action="store_true")
    p.add_argument("-R", "--recursive", action="store_true")
    p.add_argument("--tree", action="store_true")
    p.add_argument("--icons", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--git", action="store_true")
    p.add_argument("--no-color", action="store_true")
    args = p.parse_args()
    for path_str in args.paths:
        path = Path(path_str)
        if len(args.paths) > 1:
            print(f"{path_str}:")
        if args.tree:
            print_tree(path, icons=args.icons, colors=not args.no_color)
            continue
        if args.recursive:
            list_recursive(path, args)
            continue
        if path.is_file() or path.is_symlink():
            try:
                st = path.lstat()
            except FileNotFoundError:
                continue
            git = None
            if args.git:
                gitmap = get_git_status_for_dir(str(path.parent))
                git = gitmap.get(path.name)
            e = Entry(str(path.parent), path.name, st, git=git)
            print_entries([e], args)
            continue
        try:
            entries_iter = list(path.iterdir())
        except PermissionError:
            print("Permission denied:", path_str)
            continue
        entries_iter = sorted(entries_iter, key=lambda e: e.name)
        gitmap = get_git_status_for_dir(str(path)) if args.git else {}
        entries = []
        for entry in entries_iter:
            n = entry.name
            if not args.all and n.startswith("."):
                continue
            try:
                st = entry.lstat()
            except FileNotFoundError:
                continue
            link_t = None
            if stat.S_ISLNK(st.st_mode):
                try:
                    link_t = entry.readlink()
                except OSError:
                    link_t = None
            entries.append(Entry(str(entry), n, st, link_t, gitmap.get(n)))
        print_entries(entries, args)


if __name__ == "__main__":
    raise SystemExit(main())
