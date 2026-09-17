#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import pillow_heif as ph
from dh import gsz
from fastwalk import walk_files


def process_file(path) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    print(f"[OK] {path.name}")
    img = ph.open_heif(path)
    outfile = path.with_suffix(".jpg")
    img.save(outfile)
    return True


def main() -> None:
    cwd = Path().cwd()
    start_size = gsz(cwd)
    files = []
    for pth in walk_files(cwd):
        path = Path(pth)
        if path.is_file() and path.suffix in {".heif", ".heic"}:
            files.append(path)
    pool = Pool(8)
    pool.imap_unordered(process_file, files)
    pool.close()
    pool.join()
    after = gsz(cwd)
    print(f"{fornat_size(after - start_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
