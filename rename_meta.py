#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from dh import cprint, get_files, unique_path

OUT_PATH = Path("/data/data/com.termux/files/home/tmp/metadata")


def process_file(path: Path) -> bool | None:
    pkgname = ""
    path = Path(path)
    pkgversion = ""
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    line1 = lines[1]
    line2 = lines[2]
    striped1 = line1.lower().strip()
    striped2 = line2.lower().strip()
    if striped1.startswith("name:"):
        pkgname = striped1.replace("name:", "").lstrip()
    if striped2.startswith("version:"):
        pkgversion = striped2.replace("version:", "").lstrip()
    if pkgversion and pkgname:
        outfn = Path(pkgname + "-" + pkgversion + ".metadata")
        outpath = OUT_PATH / outfn
        if outpath.exists():
            outpath = unique_path(outpath)
        outpath.write_text(content, encoding="utf-8")
        cprint(f"{outfn} created.", "green")
    elif pkgname and (not pkgversion):
        outfn = Path(pkgname + ".metadata")
        outpath = OUT_PATH / outfn
        content = path.read_text(encoding="utf-8")
        if outpath.exists():
            outpath = unique_path(outpath)
        content = path.read_text(encoding="utf-8")
        outpath.write_text(content, encoding="utf-8")
        cprint(f"{outfn} created.", "yellow")
    elif not pkgname and (not pkgversion):
        cprint(f"no data{path}", "cyan")
        input("what u wanna do?")
    return None


def main() -> None:
    cwd = Path.cwd()
    for path in get_files(cwd):
        if path.is_file() and (path.name == "METADATA" or path.suffix == ".metadata"):
            process_file(path)


if __name__ == "__main__":
    raise SystemExit(main())
