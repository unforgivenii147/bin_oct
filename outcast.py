#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def copy_largest_file(source_dir, dest):
    largest = None
    max = -1
    for path in source_dir.iterdir():
        if path.is_file():
            size = path.stat().st_size
            if size > max:
                max = size
                largest = path
    if largest:
        dest.write_bytes(largest.read_bytes())
        print(f"{dest.name} ({max / (1024 * 1024)} MB)")


def get_random_filename(length: int = 6) -> str:
    from random import choice
    from string import ascii_lowercase

    letters: str = ascii_lowercase
    return "".join(choice(letters) for _ in range(length))


if __name__ == "__main__":
    source = Path("/sdcard/Android/data/org.telegram.messenger/cache")
    dest = Path(f"/sdcard/Download/{get_random_filename()}.mkv")
    copy_largest_file(source, dest)
