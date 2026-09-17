#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from lib2to3 import refactor
from pathlib import Path

from dh import get_pyfiles, mpf3

fixers = collect_fixers()


def collect_fixers():
    import pkgutil
    from lib2to3 import fixes

    fixer_names = []
    for _, modname, is_pkg in pkgutil.iter_modules(
        fixes.__path__, prefix="lib2to3.fixes."
    ):
        if not is_pkg:
            fixer_names.append(modname)
    return fixer_names


def refactor_file(path: Path) -> None:
    options = {"print_function": True}
    tool = refactor.RefactoringTool(fixers, options)
    try:
        original = path.read_text()
        tree = tool.refactor_string(original, str(path))
        new_content = str(tree)
        if original == new_content:
            print(f"  nothing changed: {path}")
        else:
            path.write_text(new_content)
            print(f"  refactored:      {path}")
    except Exception as exc:
        print(f"  ERROR {path}: {exc}", file=sys.stderr)


def main() -> None:
    cwd = Path.cwd()
    files = get_pyfiles(cwd)
    mpf3(refactor_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
