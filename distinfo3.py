#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dh import cprint

major, minor, _, _, _ = sys.version_info
py_version = f"{major}.{minor}"


def process_dir(dr: Path) -> bool:
    print(dr.name)
    if "dist-info" in dr.name:
        for k in dr.iterdir():
            if k.name in {"top_level.txt", "entry_points.txt"}:
                cprint(f"{dr} removed", "cyan")
                shutil.rmtree(dr)
    return True


def main() -> None:
    cwd = Path(f"/data/data/com.termux/files/usr/lib/python{py_version}/site-packages")
    if not cwd.exists():
        return
    for path in cwd.iterdir():
        if path.is_dir() and len(list(path.iterdir())) == 1:
            process_dir(path)


if __name__ == "__main__":
    raise SystemExit(main())
