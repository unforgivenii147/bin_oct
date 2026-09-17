#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    cwd = Path.cwd()
    binary_dir = cwd / "binary"
    binary_dir.mkdir(exist_ok=True)
    files_moved = 0
    for f in cwd.iterdir():
        if f.is_file() and is_binary(Path(f)):
            try:
                shutil.move(str(f), binary_dir / f.name)
                print(f"Moved: {f.name} -> binary/{f.name}")
                files_moved += 1
            except Exception as e:
                print(f"Failed to move {f.name}: {e}")
    if files_moved == 0:
        print("No binary files found to move.")
    else:
        print(f"Total binary files moved: {files_moved}")


if __name__ == "__main__":
    raise SystemExit(main())
