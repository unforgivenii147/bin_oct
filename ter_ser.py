#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, gsz, mpf3, rrs, runcmd

EXT = [".js", ".jsx", ".jsm", ".jsc"]


def safe_run(path: Path) -> bool:
    cmd = ["terser", "--compress", "--mangle", "--", str(path)]
    res, txt, err = runcmd(cmd, show_output=False)
    if res != 0:
        print(f"Error running terser: {err}", file=sys.stderr)
        return False
    path.write_text(txt, encoding="utf8")
    return True


def process_file(path):
    path = Path(path)
    if path.name.endswith(".min.js"):
        return
    if "site-packages" in path.parts and "notebook" in path.parts:
        return
    before = gsz(path)
    if not path.exists() or not before:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) == 1:
        del lines, before
        return
    if safe_run(path):
        after = gsz(path)
        rrs(path, before, after)
    return


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p), ext=EXT)
    else:
        files = get_files(cwd, ext=EXT)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
