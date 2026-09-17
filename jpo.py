#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, gsz, mpf3, rrs, runcmd


def process_file(path: str | Path) -> None:
    path = Path(path)
    before = gsz(path)
    try:
        cmd = [
            "jpegoptim",
            "-f",
            "-m",
            "65",
            "--max",
            "85",
            "--threshold",
            "0.7",
            "--strip-all",
            str(path),
        ]
        _ret, _txt, _err = runcmd(cmd, show_output=False)
        after = gsz(path)
        rrs(path, before, after)
        return
    except Exception:
        return


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".jpg", ".jpeg"])
    mpf3(process_file, files)
    after = gsz(cwd)
    rrs(cwd, before, after)


if __name__ == "__main__":
    raise SystemExit(main())
