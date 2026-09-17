#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import cprint, get_files, mpf3
from fontTools.ttLib import woff2

cwd = Path.cwd()


def process_file(path: Path) -> bool | None:
    path = Path(path)
    ttf_path = path.with_suffix(".ttf")
    if ttf_path.exists() and ttf_path.stat().st_size:
        print(f"{path.name} already converted.")
        return True
    try:
        woff2.decompress(path, ttf_path)
        print(f"{path.name} converted.")
        path.unlink()
    except:
        cprint(f"error convering {path.name}")


def main() -> None:
    files = get_files(cwd, ext=[".woff2"])
    _ = mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
