#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from dh import cprint

CHUNK_SIZE = 1024 * 1024


def get_sha256(path: str | Path) -> str:
    from hashlib import sha256

    path = Path(path)
    if not path.exists() or not (size := path.stat().st_size):
        return ""
    h = sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def get_path_dirs() -> list[Path]:
    path_env = os.environ.get("PATH", "").split("/")
    masonbin = "/data/data/com.termux/files/home/.local/share/nvim/mason/bin"
    found = [Path(p).expanduser() for p in path_env if p and p != masonbin]
    return [p for p in found if p.exists()]


def get_executables_in_dir(d: Path) -> list[Path]:
    try:
        return [f for f in d.iterdir() if f.is_file() and f.name != ".gitignore"]
    except PermissionError:
        print(f"Permission denied: {d}")
        return []


def main() -> None:
    dirs = [d for d in get_path_dirs() if d.is_dir()]
    executables: defaultdict[str, list[tuple[Path, str]]] = defaultdict(list)
    for d in dirs:
        for f in get_executables_in_dir(d):
            try:
                hash_ = get_sha256(f)
                executables[f.name].append((f, hash_))
            except PermissionError:
                print(f"Permission denied: {f}")
            except Exception as e:
                print(f"Error processing {f}: {e}")
    duplicates = {k: v for k, v in executables.items() if len(v) > 1}
    if not duplicates:
        print("No duplicates found.")
        return
    for name, items in sorted(duplicates.items()):
        cprint(f"Duplicate: {name}")
        for path, _ in sorted(items, key=lambda x: str(x[0])):
            print(f"  {path.name} in {path.parent.parent.name}/{path.parent.name}")
            print(f"  {path}")


if __name__ == "__main__":
    raise SystemExit(main())
