#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path

from dh import cprint, is_binary, should_skip


def get_filez(root_dir: str | Path):
    from os import walk as os_walk

    visited_dirs: set[Path] = set()
    root_dir = Path(root_dir)
    if root_dir.is_dir():
        for dirpath, dirnames, filenames in os_walk(root_dir, topdown=True):
            base_path = Path(dirpath)
            for dirname in list(dirnames):
                full_path = base_path / dirname
                resolved_path = full_path.resolve()
                if should_skip(full_path) or resolved_path in visited_dirs:
                    dirnames.remove(dirname)
                visited_dirs.add(resolved_path)
            for filename in filenames:
                path = Path(dirpath) / filename
                if not should_skip(path):
                    yield path
    else:
        yield root_dir


COLOR_RE = re.compile("#([a-fA-F0-9]{6}|[a-fA-F0-9]{3})\\b")


def pf(path: Path):
    content = path.read_text(encoding="utf-8", errors="ignore")
    found = []
    found = COLOR_RE.findall(content)
    found = list(set(found))
    if found:
        print(f"{path.name}", end=" : ")
        cprint(f"{len(found)}", "cyan")
        return found
    return []


def main() -> None:
    cwd = Path.cwd()
    outfile = cwd / "colors"
    colorz = set()
    for path in get_filez(cwd):
        if not is_binary(path):
            result = pf(path)
            if result:
                colorz.update(result)
    colors = sorted(colorz)
    fc = len(colors)
    for c in colors:
        if len(c) == 3:
            normed = c * 2
            colors.append(normed)
    finals = []
    for k in sorted(set(colors)):
        if len(k) == 3:
            continue
        finals.append(k)
    finals = sorted(set(finals))
    outfile.write_text("\n".join(finals), encoding="utf-8")
    cprint(f"{fc} colors found", "green")


if __name__ == "__main__":
    raise SystemExit(main())
