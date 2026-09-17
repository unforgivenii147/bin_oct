#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def main() -> None:
    count = 0
    root = Path.cwd()
    dirs = [p for p in root.rglob("*") if p.is_dir()]
    dirs.sort(key=lambda p: len(p.parts), reverse=True)
    for dir_path in dirs:
        try:
            dir_path.rmdir()
            print(f"removing empty dir: {dir_path}")
            count += 1
        except OSError:
            pass
    print(f"total {count} empty dirs removed")


if __name__ == "__main__":
    raise SystemExit(main())
