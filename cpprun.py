#!/data/data/com.termux/files/home/.local/bin/python
"""
Termux-friendly C / C++ runner using the `sh` library.
Usage: cpprun <file.c|file.cpp|file.cc> [args...]

Install:  pip install sh
"""

import os
import stat
import sys
from pathlib import Path

import sh  # pip install sh


COMPILERS = {
    ".c": ("clang", ("clang", "gcc")),
    ".cpp": ("clang++", ("clang++", "g++")),
    ".cc": ("clang++", ("clang++", "g++")),
    ".cxx": ("clang++", ("clang++", "g++")),
}


def _pick_compiler(candidates):
    """Return the first candidate available on PATH, or None."""
    for c in candidates:
        if sh.which(c):
            return c
    return None


def cpp_run(*args):
    if not args:
        print("Usage: cpprun <file.c|file.cpp|file.cc> [args...]")
        return 1

    src = Path(args[0]).expanduser().resolve()
    if not src.is_file():
        print(f"Error: {src} not found", file=sys.stderr)
        return 1

    ext = src.suffix.lower()
    if ext not in COMPILERS:
        print(
            f"Error: unsupported extension '{ext}'. "
            f"Expected one of: {', '.join(COMPILERS)}",
            file=sys.stderr,
        )
        return 1

    preferred, fallbacks = COMPILERS[ext]
    compiler_name = _pick_compiler((preferred, *fallbacks))
    if compiler_name is None:
        print("Error: no compiler found. Run: pkg install clang", file=sys.stderr)
        return 1

    # Android won't execute binaries from shared storage, so put the exe
    # somewhere safe: $TMPDIR -> $PREFIX/tmp -> home.
    tmpdir = Path(
        os.environ.get("TMPDIR")
        or f"{os.environ.get('PREFIX', '/data/data/com.termux/files/usr')}/tmp"
        or Path.home()
    )
    tmpdir.mkdir(parents=True, exist_ok=True)
    exe = tmpdir / src.stem

    # --- Compile ----------------------------------------------------------
    std_flag = "-std=c17" if ext == ".c" else "-std=c++17"
    compiler = sh.Command(compiler_name)
    try:
        compiler(
            std_flag,
            "-Wall",
            "-Wextra",
            "-O2",
            str(src),
            "-o",
            str(exe),
            # Forward compiler stdout/stderr so the user sees errors.
            _out=sys.stdout,
            _err=sys.stderr,
        )
    except sh.ErrorReturnCode as e:
        # Errors already printed; just propagate the exit status.
        return e.exit_code
    except sh.CommandNotFound:
        print(f"Error: {compiler_name} not found on PATH", file=sys.stderr)
        return 1

    # Some Android filesystems strip the exec bit.
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # --- Run --------------------------------------------------------------
    try:
        prog = sh.Command(str(exe))
        prog(
            *args[1:],
            _in=sys.stdin,
            _out=sys.stdout,
            _err=sys.stderr,
        )
    except sh.ErrorReturnCode as e:
        return e.exit_code
    except KeyboardInterrupt:
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(cpp_run(*sys.argv[1:]))
