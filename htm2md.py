#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import get_files, mpf3, runcmd


def process_file(path) -> tuple[Path, bool]:
    path = Path(path)
    if path.suffix.lower() in {".html", ".htm"}:
        md_file = path.with_suffix(".md")
    else:
        return (path, False)
    try:
        _, txt, _ = runcmd(["rhtml2md", str(path)], show_output=False)
        md_file.write_text(txt, encoding="utf-8")
        print(f"✓ Converted: {path.name} -> {md_file.name}")
        return (md_file, True)
    except Exception as e:
        print(f"✗ Unexpected error converting {path}: {e}", file=sys.stderr)
        return (path, False)


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
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
