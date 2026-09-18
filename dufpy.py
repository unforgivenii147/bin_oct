#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from pathlib import Path

from dh import cprint, get_pyfiles, mpf
from xxhash import xxh64_hexdigest


def process_file(path: str | Path) -> tuple[str, str]:
    """Parse a Python file, normalize it via AST, and return (hash, path)."""
    p = Path(path)
    code = p.read_text(encoding="utf-8")
    parsed = ast.parse(code)
    unparsed = ast.unparse(parsed)
    digest = xxh64_hexdigest(unparsed.encode("utf-8"))
    return digest, str(p)


def main() -> None:
    cwd: Path = Path.cwd()
    files: list[Path] = list(get_pyfiles(cwd))

    file_dict: dict[str, list[str]] = {}
    results: list[tuple[str, str]] = mpf(process_file, files)

    for digest, path in results:
        file_dict.setdefault(digest, []).append(path)

    for digest, paths in file_dict.items():
        if len(paths) > 1:
            print(f"files with hash: {digest}")
            for path in paths:
                print(f"  - {path}")

    deleted: int = 0
    for paths in file_dict.values():
        if len(paths) <= 1:
            continue
        for path in paths[1:]:
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()
                print(f"{path} removed")
                deleted += 1

    if deleted:
        cprint(f"{deleted} files removed.", "cyan")


if __name__ == "__main__":
    raise SystemExit(main())
