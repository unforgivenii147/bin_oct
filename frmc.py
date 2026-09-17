#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import sys
from pathlib import Path

from dh import cprint, fsz, get_nobinary, gsz, is_binary, mpf3, remove_blank_lines


def process_file(path: Path) -> None:
    path = Path(path)
    if path.suffix == ".md":
        return
    removed: int = 0
    inline: int = 0
    if is_binary(path) or path.suffix in SOURCE_CODE_EXT:
        print(f"[skip] {path.name} is binary or source code")
        return
    before: int = gsz(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    print(f"{path.name}", end="|")
    if not lines:
        return
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#!") or "#!" in stripped:
            cleaned.append(line)
            continue
        if "#" in stripped and (not stripped.startswith("#")):
            indx = line.index("#")
            cleaned.append(line[:indx] + "\n")
            inline += 1
            continue
        if not stripped.startswith("#"):
            cleaned.append(line)
        else:
            removed += 1
    code = "".join(cleaned)
    code = remove_blank_lines(code)
    if path.suffix == ".py":
        try:
            _ = ast.parse(code)
            path.write_text(code, encoding="utf-8")
            diffsize = before - gsz(path)
            cprint(f"{fsz(diffsize)}|removed :{removed}|inline :{inline}", "yellow")
        except:
            cprint("result code invalid.", "magenta")
            return
    else:
        path.write_text(code, encoding="utf-8")
        diffsize = before - gsz(path)
        cprint(f"{fsz(diffsize)}|removed :{removed}|inline :{inline}", "yellow")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_nobinary(cwd)
    if not files:
        print("no files found")
        return
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    before = gsz(cwd)
    _ = mpf3(process_file, files)
    diffsize = before - gsz(cwd)
    cprint(f"{fsz(diffsize)}", "cyan")


if __name__ == "__main__":
    raise SystemExit(main())
