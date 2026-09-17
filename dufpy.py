#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from pathlib import Path

from dh import cprint, get_pyfiles
from xxhash import xxh64_hexdigest


def process_file(path) -> tuple[str, Path]:
    path = Path(path)
    return (
        xxh64_hexdigest(ast.unparse(ast.parse(path.read_text(encoding="utf-8")))),
        path,
    )


def main() -> None:
    cwd = Path.cwd()
    files = get_pyfiles(cwd)
    fd = {}
    results = mpf3(process_file, files)
    for result in results:
        hash, path = result
        fd.setdefault(hash, []).append(path)
    for h, p in fd.items():
        if len(p) > 1:
            print(f"files with hash: {h}")
            for path in p:
                print(f"  - {path}")
                path.unlink()
    deleted = 0
    for h, p in fd.items():
        if len(p) > 1:
            for path in p[1:]:
                deleted += 1
                if path.exists():
                    path.unlink()
    if deleted:
        cprint(f"{deleted} files removed.", "cyan")


if __name__ == "__main__":
    raise SystemExit(main())
