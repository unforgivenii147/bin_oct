#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def main() -> None:
    count = 0
    root = Path.cwd()
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            print(f"removing empty dir: {path}")
            path.rmdir()
            count += 1
    print(f"total {count} empty dirs removed")


if __name__ == "__main__":
    raise SystemExit(main())
