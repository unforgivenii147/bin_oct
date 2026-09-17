#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import gsz, mpf3, rrs, runcmd, should_skip
from fastwalk import walk_files


def process_file(path: str | Path) -> None:
    path = Path(path)
    before = gsz(path)
    try:
        cmd = [
            "pngquant",
            "--force",
            "--skip-if-larger",
            "--quality=60-70",
            "--strip",
            str(path),
            "--output",
            str(path),
        ]
        _ret, _txt, _err = runcmd(cmd, show_output=False)
        after = gsz(path)
        rrs(path, before, after)
        return
    except Exception:
        return


def get_files(root_dir):
    for path in walk_files(root_dir):
        if should_skip(path):
            continue
        if path.is_file() and path.suffix in {".png", ".PNG"}:
            yield path


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
