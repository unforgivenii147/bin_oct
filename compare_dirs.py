#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shlex
import stat
import sys
from hashlib import sha256
from pathlib import Path

from dh import cprint

CHUNK_SIZE = 32768


def get_sha256(path: str | Path) -> str:
    path = Path(path)
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def write_shell_copy(
    script_path: Path, src_root: Path, dst_root: Path, only_dirs, only_files
) -> None:
    with script_path.open("w", encoding="utf-8") as sh:
        sh.write("#!/bin/sh\n")
        for d in sorted(only_dirs):
            dst_dir = dst_root / d
            sh.write(f"mkdir -p {shlex.quote(str(dst_dir))}\n")
        for f in sorted(only_files):
            dst_file = dst_root / f
            src_file = src_root / f
            parent = dst_file.parent
            sh.write(
                f"""mkdir -p {shlex.quote(str(parent))} && cp -a {shlex.quote(str(src_file))} {shlex.quote(str(dst_file))}
"""
            )
    st = script_path.stat()
    script_path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    cwd = Path.cwd()
    dir1 = sys.argv[1].strip()
    dir2 = sys.argv[2].strip()
    first = Path(dir1).expanduser() if "~" in dir1 else Path(dir1)
    second = Path(dir2).expanduser() if "~" in dir2 else Path(dir2)
    f_files = [p.name for p in first.glob("*") if p.is_file()]
    [p.name for p in first.glob("*") if p.is_dir()]
    s_files = [p.name for p in second.glob("*") if p.exists() and p.is_file()]
    [p.name for p in second.glob("*") if p.is_dir()]
    common1 = [(Path(dir1).resolve() / p) for p in f_files if p in s_files]
    common2 = {
        str(Path(dir1).resolve() / p): str(Path(dir2).resolve() / p)
        for p in f_files
        if p in s_files
    }
    if common1:
        for k in common1:
            print(f"  - {k}")
    else:
        print("no common files")
        sys.exit(1)
    only_files_first = [p for p in f_files if p not in s_files]
    [p for p in s_files if p not in f_files]
    common_txt = cwd / "common.txt"
    common_txt.write_text("\n".join([str(p) for p in common1]))
    ans = input(f"delete from {dir1}  ? ")
    if ans == "y":
        for k, v in common2.items():
            if get_sha256(k) == get_sha256(v):
                print(f"the files are identical \n{k}\n{v}")
                Path(k).unlink()
            else:
                print(f"similar name filed:\n{k}\n{v}\n")
    cprint("only in first")
    for p in only_files_first:
        print(p)


if __name__ == "__main__":
    raise SystemExit(main())
