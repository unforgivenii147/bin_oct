#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import get_files, is_binary

SIZE_THRESHOLD = 100
LINE_THRESHOLD = 3


def process_file(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    number_of_lines = len(content.splitlines())
    if len(content) < SIZE_THRESHOLD or number_of_lines < LINE_THRESHOLD:
        del content, number_of_lines
        path.unlink()
        print(f"{path.name} removed")


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd)
    for path in files:
        if is_binary(path):
            print(f"{path.name} is binary")
            continue
        process_file(path)


if __name__ == "__main__":
    raise SystemExit(main())
