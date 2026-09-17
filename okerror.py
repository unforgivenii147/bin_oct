#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ERROR_DIR = Path("error")
OK_DIR = Path("ok")


def ensure_dirs() -> None:
    ERROR_DIR.mkdir(exist_ok=True)
    OK_DIR.mkdir(exist_ok=True)


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 1
    while True:
        new_dest = parent / f"{stem}_{counter}{suffix}"
        if not new_dest.exists():
            return new_dest
        counter += 1


def black_check(path: Path) -> bool:
    result = subprocess.run(["black", "--check", str(path)], capture_output=True)
    return result.returncode == 0


def main() -> None:
    ensure_dirs()
    for py_file in Path().glob("*.py"):
        if py_file.name == Path(__file__).name:
            continue
        print(f"Checking {py_file}...")
        if black_check(py_file):
            dest = unique_destination(OK_DIR / py_file.name)
            print(f"  ✓ OK → {dest}")
        else:
            dest = unique_destination(ERROR_DIR / py_file.name)
            print(f"  ✗ ERROR → {dest}")
        shutil.move(str(py_file), str(dest))


if __name__ == "__main__":
    raise SystemExit(main())
