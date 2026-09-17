#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, get_files, gsz, mpf3, runcmd

START_DIR = Path.cwd()
NUM_PROCESSES = 4


def process_file(path: str | Path) -> None:
    path = Path(path)
    before = gsz(path)
    try:
        cmd = ["optipng", "-o7", str(path)]
        _ret, txt, _err = runcmd(cmd, show_output=True)
        if "skipping" in txt.lower():
            print(f" Skipped: {path.name}")
            return
        after = gsz(path)
        dz = before - after
        if not dz:
            print(f"✅ : {path.name} : (no change)")
            return
        ratio = after / before * 40
        print(f"✅ : {path.name}", end=" | ")
        cprint(f"{ratio:.1f} %")
        return
    except FileNotFoundError:
        print(
            "❌ Error: 'pngquant' command not found. Please ensure the 'pngquant' binary is installed and in your system PATH."
        )
    except Exception as e:
        print(f"❌ Error compressing {path}: {e}")
    return


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p, ext=[".png", ".PNG"]))
    else:
        files = get_files(cwd, ext=[".png", ".PNG"])
    _ = mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
