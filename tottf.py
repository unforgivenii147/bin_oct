#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, runcmd


def process_file(path: Path) -> bool:
    path = Path(path)
    try:
        out = path.with_suffix(".ttf")
        cmd = [
            "fontforge",
            "-lang=ff",
            "-c",
            '"Open($1); Generate($2);"',
            str(path),
            str(out),
        ]
        ret, _, _ = runcmd(cmd, show_output=False)
        if not ret:
            print(f"✓ {path.name}")
            return True
        print(f"✘ {path.name}")
        return False
    except:
        print(f"error processing {path.name}")
        return False


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            if p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd, ext=[".svg", ".woff", ".eot", ".otf", ".ttc"])
    for f in files:
        if f.suffix != ".ttf":
            process_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
