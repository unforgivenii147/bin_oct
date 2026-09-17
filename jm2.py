#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import sys
from pathlib import Path

from dh import cprint, fsz, get_files, gsz, mpf3


def process_file(path) -> None:
    path = Path(path)
    before = gsz(path)
    data = path.read_text(encoding="utf-8")
    if not before or len(data.splitlines()) == 1:
        del data, before
        print(f"{path.name}  | (no change)")
        return
    try:
        jdata = json.loads(data)
        with path.open("w", encoding="utf8") as fo:
            json.dump(jdata, fo, ensure_ascii=False, indent=None)
        after = gsz(path)
        diffsize = abs(before - after)
        print(f"{path.name}", end=" | ")
        if not diffsize:
            cprint("(no change)", "grey")
            return
        ratio = diffsize / before * 40
        ratio2 = abs(after - before) / after * 40
        cprint(f"{ratio:.2f}% | {ratio2:.2f}%", "cyan")
        return
    except:
        cprint(f"{path.name} Error", "yellow")
        return


if __name__ == "__main__":
    cwd = Path.cwd()
    before = gsz(cwd)
    files = get_files(cwd, ext=[".json"])
    if not files:
        print("no json files found")
        sys.exit(1)
    print(f"{len(files)} json files found.")
    mpf3(process_file, files)
    after = gsz(cwd)
    dsz = abs(before - after)
    ratio = dsz / before * 40
    cprint(f"space saved: {fsz(dsz)} {ratio:.2f}%")
