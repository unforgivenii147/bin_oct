#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from multiprocessing import Pool, cpu_count
from pathlib import Path

FILE_EXTENSIONS = [".pyc", ".log", ".bak"]
DIR_NAMES = ["__pycache__", ".ruff_cache", ".mypy_cache"]


def remove_path(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
            print(f"Removed file: {path.name}")
        elif path.is_dir():
            shutil.rmtree(path)
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"Removed directory: {rel}")
    except Exception as e:
        print(f"Failed to remove {path}: {e}")


def scan_and_remove(base_path: Path):
    try:
        for item in base_path.iterdir():
            if item.is_file():
                if any(item.name.endswith(ext) for ext in FILE_EXTENSIONS):
                    yield item
            elif item.is_dir():
                if item.name in DIR_NAMES:
                    if item.parent.name == "site-packages":
                        print(f"not allowed: {item}")
                        continue
                    yield item
                else:
                    yield from scan_and_remove(item)
    except PermissionError:
        pass


def main() -> None:
    base_path = Path.cwd().resolve()
    with Pool(cpu_count()) as pool:
        pool.map(remove_path, scan_and_remove(base_path))


if __name__ == "__main__":
    raise SystemExit(main())
