#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def main() -> None:
    cwd = Path.cwd()
    ext1 = input("ext 1 :").strip()
    ext2 = input("ext 2 :").strip()
    choice = input("remove which one: 1 or 2: ").strip()
    if not ext1.startswith("."):
        ext1 = "." + ext1
    if not ext2.startswith("."):
        ext2 = "." + ext2
    todel = ext1 if choice == "1" else ext2
    for path in cwd.rglob(f"*{ext1}"):
        if path.is_file() and path.suffix == ext1:
            twin = path.with_suffix(ext2)
            if twin.exists():
                if todel == ext1:
                    print(f"[✖] {path}  (keeping {twin})")
                    path.unlink()
                else:
                    print(f"[✖] {twin}  (keeping {path})")
                    twin.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
