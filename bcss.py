#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, fsz, get_files, gsz, mpf3, runcmd


def process_file(path) -> bool | None:
    path = Path(path)
    before = gsz(path)
    if not path.exists():
        return False
    print(f"{path.name}", end=" ")
    cmd = ["cleancss", "--format", "beautify", str(path), "-o", str(path)]
    res, _, _err = runcmd(cmd, show_output=True)
    if not res:
        after = gsz(path)
        diffsize = before - after
        if not diffsize:
            cprint("[NO CHANGE]", "white")
            return
        if diffsize:
            ratio = diffsize / before * 40
            cprint(f"[OK] - {fsz(diffsize)} {abs(ratio):.1f}%", "cyan")
        return
    cprint("[ERROR]", "red")
    return


def main() -> None:
    args = sys.argv[1:]
    cwd = Path.cwd()
    before = gsz(cwd)
    files = (
        [Path(p) for p in args] if args else get_files(cwd, ext=[".css", ".min.css"])
    )
    _ = mpf3(process_file, files)
    diff_size = before - gsz(cwd)
    cprint(f"space freed : {fsz(diff_size)}", "green")


if __name__ == "__main__":
    raise SystemExit(main())
