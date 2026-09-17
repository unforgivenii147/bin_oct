#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from pathlib import Path

from dh import cprint, get_pyfiles, mpf
from xxhash import xxh64_hexdigest


def process_file(path) -> tuple[str, str]:
    path = Path(path)
    code = path.read_text(encoding="utf-8")
    parsed = ast.parse(code)
    unparsed = ast.unparse(parsed)
    return xxh64_hexdigest(unparsed.encode("utf-8")), str(path)


def main() -> None:
    cwd = Path.cwd()
    files = get_pyfiles(cwd)
    fd = {}
    results = mpf(process_file, files)
    for result in results:
        hash, path = result
        fd.setdefault(hash, []).append(path)
    for h, p in fd.items():
        if len(p) > 1:
            print(f"files with hash: {h}")
            for path in p:
                print(f"  - {path}")
    deleted = 0
    for h, p in fd.items():
        if len(p) > 1:
            for path in p[1:]:
                deleted += 1
                if Path(path).exists():
                    #                    Path(path).unlink()
                    print(f"{path} removed")
    if deleted:
        cprint(f"{deleted} files removed.", "cyan")


if __name__ == "__main__":
    raise SystemExit(main())
