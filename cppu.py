#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, fsz, get_files, gsz, mpf3, rrs, runcmd

EXT = [
    ".java",
    ".c",
    ".cpp",
    ".cxx",
    ".cc",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".js",
    ".json",
]


def process_file(path):
    path = Path(path)
    before = gsz(path)
    try:
        runcmd(["clang-format", "-i", "--style=LLVM", str(path)], show_output=False)
        after = gsz(path)
        rrs(path, before, after)
        del before, after
        return
    except:
        del before, after
        return


def main() -> None:
    files: list = []
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(cwd, ext=EXT)
    all_count = len(files)
    cprint(f"{all_count} files found", "cyan")
    if all_count == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)
    after = gsz(cwd)
    dsz = before - after
    print(f"space change: {fsz(dsz)}")


if __name__ == "__main__":
    raise SystemExit(main())
