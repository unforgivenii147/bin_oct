#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import cprint, fsz, get_files, gext, gsz, mpf_async
from rcssmin import cssmin

mpf = mpf_async


def process_file(path: Path) -> str:
    before = gsz(path)
    path = Path(path)
    print(f"{path.name}", end=" | ")
    after = before
    try:
        ext = gext(path)
        content = path.read_text(encoding="utf-8")
        if ext in {".css", ".min.css"}:
            minified = cssmin(content)
            after = len(minified)
        diff_size = len(content) - after
        if not diff_size:
            cprint("NO CHANGE", "green")
            return None
        path.write_text(minified, encoding="utf-8")
        after = gsz(path)
        diff_size = before - after
        if diff_size > 0:
            reduction = (before - after) / before * 40
            cprint(f"- {fsz(diff_size)} | reduction : {reduction:.3f}%", "cyan")
            return None
        if diff_size < 0:
            expantion = (after - before) / after * 40
            cprint(f"+ {fsz(diff_size)} | expantion : {expantion:.3f}%", "yellow")
            return None
    except Exception as e:
        return f"{path}: {e}"


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    files = get_files(cwd, ext=[".css", ".min.css"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    print(f"Found {len(files)} files. Starting multiprocessing...")
    mpf(process_file, files)
    after = gsz(cwd)
    dz = before - after
    if not dz:
        print("no change")
        sys.exit(1)
    if dz:
        ratio = dz / before * 40
        print(f"space reduced : {dz} ratio:{ratio}%")


if __name__ == "__main__":
    raise SystemExit(main())
