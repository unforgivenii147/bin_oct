#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

EXCLUDE_DIRS = {".git"}
OUTPUT_FILE = Path("/sdcard/all2.txt")


def read_file(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def collect_files(root: Path):
    try:
        for item in root.iterdir():
            if item.is_dir():
                if item.name not in EXCLUDE_DIRS:
                    yield from collect_files(item)
            elif item.is_file():
                if item.resolve() == OUTPUT_FILE.resolve():
                    continue
                if "license" in item.name.lower():
                    yield item
    except PermissionError:
        pass


def build_all_txt(root_path: str) -> None:
    root = Path(root_path)
    files = list(collect_files(root))
    print(f"Found {len(files)} files")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as out:
        for i, path in enumerate(files, 1):
            content = read_file(path)
            if content is None:
                print(f"Skipping unreadable file: {path}")
                continue
            out.write(content)
            if i != len(files):
                out.write("\n\n\n")
            print(f"Added: {path}")
    print(f"\nFinished: {OUTPUT_FILE} created.")


if __name__ == "__main__":
    build_all_txt(".")
