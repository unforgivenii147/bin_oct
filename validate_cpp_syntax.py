#!/data/data/com.termux/files/home/.local/bin/python
"""
Auto syntax-checker for C/C++/header files in Termux (or any Unix with clang).

Usage:
    ./syntax_check.py [files_or_dirs ...]

If no paths are given, scans the current directory (non-recursive) for
*.c, *.cpp, *.h, *.hpp files.

Reports only files that fail. Uses multiprocessing with 8 workers.
"""

import subprocess
import sys
import multiprocessing as mp
from pathlib import Path

CPP_EXTS = {".cpp", ".cc", ".cxx"}
C_EXTS = {".c"}
HEADER_CPP_EXTS = {".hpp", ".hh", ".hxx"}
HEADER_C_EXTS = {".h"}

ALL_EXTS = CPP_EXTS | C_EXTS | HEADER_CPP_EXTS | HEADER_C_EXTS

NUM_WORKERS = 8


def run(cmd, input_bytes=None):
    """Run a command, return (returncode, combined_output)."""
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return proc.returncode, proc.stdout.decode(errors="replace")
    except FileNotFoundError as e:
        return 127, f"command not found: {e}"


def check_file(path: Path):
    """
    Returns (path, ok: bool, output: str).
    Chooses the right command based on extension.
    """
    ext = path.suffix.lower()

    if ext in CPP_EXTS:
        cmd = [
            "clang++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fsyntax-only",
            str(path),
        ]
        rc, out = run(cmd)
    elif ext in C_EXTS:
        cmd = ["clang", "-std=c11", "-Wall", "-Wextra", "-fsyntax-only", str(path)]
        rc, out = run(cmd)
    elif ext in HEADER_CPP_EXTS:
        # echo '#include "file.hpp"' | clang++ -x c++ -fsyntax-only -
        include_line = f'#include "{path.name}"\n'.encode()
        cmd = ["clang++", "-x", "c++", "-fsyntax-only", "-", "-I", str(path.parent)]
        rc, out = run(cmd, input_bytes=include_line)
    elif ext in HEADER_C_EXTS:
        include_line = f'#include "{path.name}"\n'.encode()
        cmd = ["clang", "-x", "c", "-fsyntax-only", "-", "-I", str(path.parent)]
        rc, out = run(cmd, input_bytes=include_line)
    else:
        return path, True, ""  # skip unknown

    return path, rc == 0, out


def gather_files(paths):
    """Expand given paths into a list of source file Paths."""
    files = []
    if not paths:
        # current dir, non-recursive
        cwd = Path.cwd()
        for p in sorted(cwd.iterdir()):
            if p.is_file() and p.suffix.lower() in ALL_EXTS:
                files.append(p)
        return files

    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in ALL_EXTS:
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            print(f"warning: skipping non-existent path: {arg}", file=sys.stderr)
    return files


def main():
    args = sys.argv[1:]
    files = gather_files(args)

    if not files:
        print("No C/C++/header files found.", file=sys.stderr)
        return 0

    print(
        f"Checking {len(files)} file(s) with {NUM_WORKERS} workers...", file=sys.stderr
    )

    failures = 0
    with mp.Pool(processes=NUM_WORKERS) as pool:
        for path, ok, output in pool.imap_unordered(check_file, files):
            if not ok:
                failures += 1
                print(f"\n=== FAIL: {path} ===")
                print(output.rstrip())

    if failures == 0:
        print("\nAll files passed syntax check.", file=sys.stderr)
    else:
        print(f"\n{failures} file(s) failed.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
