#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path

from dh import cprint, fsz, get_files, gsz, mpf3

blank_line = "\n"
IMAGE_RE = re.compile(r"^\s*(\.\.\s+image::|:target:|:alt:)", re.IGNORECASE)


def process_file(path: str | Path) -> None:
    path = Path(path)
    print(f"Processing {path.name}")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠️  Skipping {path}: {e}")
        return
    lines = content.splitlines(keepends=True)
    replaced_count = 0
    nl = []
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.lower().startswith("classifier"):
            nl.append("\n")
            replaced_count += 1
            continue
        if stripped.startswith("[![") or stripped.lower().startswith("project-url"):
            nl.append("\n")
            replaced_count += 1
            continue
        if stripped.startswith(
            (
                "Metadata-Version",
                "Home-page",
                "Author",
                "Maintainer",
                "License",
                "Platform",
                "Requires-Python",
                "Description-Content-Type",
                "Provides-Extra",
            )
        ):
            nl.append("\n")
            replaced_count += 1
            continue
        if IMAGE_RE.match(stripped):
            nl.append("\n")
            replaced_count += 1
            continue
        nl.append(line)
    if not replaced_count:
        return
    new_content = "".join(nl)
    if replaced_count:
        path.write_text(new_content, encoding="utf-8")
        print(f"✅ {path.name}", end="")
        cprint(f"{replaced_count}", "cyan")
        return
    print(f"❌ {path.name}: (no change)")


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = (
        [Path(f) for f in args] if args else get_files(cwd, ext=[".metadata", ".md"])
    )
    metafiles = list(cwd.rglob("METADATA"))
    if metafiles:
        files.extend(metafiles)
    print(f"{len(files)} files found.")
    _ = mpf3(process_file, files)
    diff_size = before - gsz(cwd)
    print(f"space saved : {fsz(diff_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
