#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from packaging.tags import parse_tag
from packaging.utils import canonicalize_name
from packaging.version import Version

MOVE_MODE = "-m" in sys.argv
WHEEL_PATTERN = re.compile(
    r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])-([^-]+)-(\d[^-]*)-([^-]+)-([^-]+)-([^-]+)\.whl$",
    re.IGNORECASE,
)


def is_valid2(path: Path) -> bool:
    filename = path.name
    return WHEEL_PATTERN.match(filename) is not None


def is_valid(path: Path) -> bool:
    filename = path.name
    try:
        basename = filename[:-4]
        parts = basename.split("-")
        if len(parts) != 5:
            return False
        dist_name, version, build_tag, py_tag, abi_platform = parts
        if canonicalize_name(dist_name) != dist_name.lower():
            return False
        try:
            Version(version)
        except Exception:
            return False
        if not build_tag[0].isdigit():
            return False
        try:
            parse_tag(py_tag + "-" + abi_platform + "-" + abi_platform.split("-")[-1])
        except Exception:
            return False
        return True
    except Exception:
        return False


def main() -> None:
    print("to move wheels with invalid name rerun with -m")
    invalid_dir = Path("invalid_wheels")
    cwd = Path.cwd()
    for path in cwd.glob("*.whl"):
        if not is_valid(path) or not is_valid2(path):
            print(f"Invalid wheel name: {path}")
            if MOVE_MODE:
                invalid_dir.mkdir(exist_ok=True)
                dest = invalid_dir / path.name
                shutil.move(str(path), str(dest))


if __name__ == "__main__":
    raise SystemExit(main())
