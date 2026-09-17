#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import get_fast, gsz, rrs, runcmd


def process_file(path) -> None:
    path = Path(path)
    if "lazy" in path.parts:
        return
    before = gsz(path)
    if not before or len(path.read_text().splitlines()) == 1:
        return
    try:
        runcmd(["svgo", str(path)], show_output=False)
        after = gsz(path)
        rrs(path, before, after)
        return
    except:
        return


def main() -> None:
    cwd = Path.cwd()
    for f in get_fast(cwd):
        if f.suffix in {".svg", ".SVG"}:
            process_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
