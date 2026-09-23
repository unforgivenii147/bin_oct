#!/data/data/com.termux/files/home/.local/bin/python
"""
mkx.py — make files in the current directory tree executable.

Behaviors merged from two original scripts and applied in a single pass:
  * suffix mode (from make_executable.py): files whose suffix is in
    {.py,.sh,.bash,.pl,.rb,.pyw,.txt}, or files with no suffix, AND that
    start with a shebang ("#!").
  * heuristic mode (from mkx.py): files inside a bin/sbin/.bin directory,
    *.so* libraries, shebang files, or binary files with no suffix.

Runs recursively from the current working directory, updates in place,
skips .git and symlinks, uses a fixed 8-worker multiprocessing pool.

Usage:
    python mkx.py
"""

import multiprocessing as mp
import os
import re
from pathlib import Path

SUFFIXES = {".py", ".sh", ".bash", ".pl", ".rb", ".pyw", ".txt"}
BIN_DIRS = {"sbin", "bin", ".bin"}
SO_RE = re.compile(r".*\.so(?:\.\d+)*$")
WORKERS = 8


def has_shebang(p):
    try:
        with p.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def is_binary(p):
    try:
        with p.open("rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return False


def is_executable(p):
    try:
        return bool(p.stat().st_mode & 0o100)
    except OSError:
        return False


def chmod_x(p):
    try:
        p.chmod(p.stat().st_mode | 0o111)
        return True
    except OSError:
        return False


def should_execute(p):
    """Union of both original selection rules."""
    # suffix-mode rule: whitelisted suffix (or none) + shebang
    if has_shebang(p):
        return True
    # heuristic-mode rules
    if p.parent.name in BIN_DIRS:
        return True
    if SO_RE.match(p.name):
        return True
    if not p.suffix and is_binary(p):
        return True
    return False


def process(path_str):
    """Worker. Returns (path_str, changed, error)."""
    p = Path(path_str)
    try:
        if not p.is_file():
            return path_str, False, None
        if is_executable(p):
            return path_str, False, None
        if not should_execute(p):
            return path_str, False, None
        if os.name != "posix":
            return path_str, False, None
        if chmod_x(p):
            return path_str, True, None
        return path_str, False, "chmod failed"
    except Exception as e:
        return path_str, False, str(e)


def main():
    root = Path.cwd()
    self_path = Path(__file__).resolve()

    files = []
    for p in root.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_symlink():
            continue
        try:
            if p.resolve() == self_path:
                continue
        except OSError:
            pass
        if p.is_file():
            files.append(str(p))

    if not files:
        print("No files found.")
        return 0

    changed = errors = 0
    with mp.Pool(processes=WORKERS) as pool:
        results = [pool.apply_async(process, (f,)) for f in files]
        for r in results:
            path_str, did_change, err = r.get()
            if err:
                errors += 1
                print(f"ERROR {path_str}: {err}")
                continue
            if did_change:
                changed += 1
                print(f"[+] Made executable: {path_str}")

    print(f"Done. changed={changed} errors={errors}")
    if os.name != "posix":
        print("Note: non-POSIX system — executable bits not applied.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
