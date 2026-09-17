#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import random
import string
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from loguru import logger

# ---- loguru setup: log to file (and stderr) ----
logger.remove()
logger.add(
    "check_modules.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    encoding="utf-8",
    backtrace=True,
    diagnose=True,
)
logger.add(
    sys.stderr,
    level="INFO",
    format="<level>{level:<8}</level> | {message}",
)


def site_packages_dirs() -> list[Path]:
    """Return existing site-packages directories."""
    import site

    dirs = []
    for p in site.getsitepackages():
        pp = Path(p)
        if pp.is_dir():
            dirs.append(pp)
    # user site (optional)
    try:
        us = Path(site.getusersitepackages())
        if us.is_dir():
            dirs.append(us)
    except Exception:
        pass
    return dirs


def iter_py_files(roots: list[Path]):
    for root in roots:
        logger.debug(f"Scanning {root}")
        yield from root.rglob("*.py")


def check_file(file: Path) -> bool:
    """Try to import/execute a file. Return True on success."""
    module_name = "".join(random.choice(string.ascii_letters) for _ in range(20))
    try:
        SourceFileLoader(module_name, str(file)).load_module()
        logger.success(f"OK   {file}")
        return True
    except Exception:
        logger.error(f"FAIL {file}")
        logger.opt(exception=True).debug("Traceback:")
        return False


if __name__ == "__main__":
    # If paths given on CLI, use them; otherwise scan site-packages
    args = sys.argv[1:]
    if args:
        files = [Path(a) for a in args]
    else:
        roots = site_packages_dirs()
        if not roots:
            logger.error("No site-packages directories found.")
            sys.exit(2)
        print(f"Site-packages roots: {[str(r) for r in roots]}")
        files = list(iter_py_files(roots))

    print(f"Checking {len(files)} file(s)...")

    has_failure = False
    ok = 0
    fail = 0
    for f in files:
        if not f.is_file() or f.suffix != ".py":
            logger.debug(f"Skip (not a .py file): {f}")
            continue
        if check_file(f):
            ok += 1
        else:
            has_failure = True
            fail += 1

    print(f"Done. OK={ok} FAIL={fail} TOTAL={ok + fail}")
    sys.exit(1 if has_failure else 0)
