#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path


def process_file(path: str) -> None:
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    for line in lines:
        if 'name = "' in line:
            pkg_name = line.split('name = "')[1].split('"')[0]
            print(pkg_name)
            with Path("requirements.txt").open("a", encoding="utf-8") as f:
                f.write(pkg_name + "\n")


def main() -> None:
    process_file("uv.lock")


if __name__ == "__main__":
    raise SystemExit(main())
