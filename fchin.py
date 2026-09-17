#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

TARGET_SUBDIR = "chinese_files"


def has_chinese_chars_in_text(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            13312 <= code <= 19903
            or 19968 <= code <= 40959
            or 63744 <= code <= 64255
            or (131072 <= code <= 173791)
            or (173824 <= code <= 177983)
            or (177984 <= code <= 178207)
            or (178208 <= code <= 183983)
            or (183984 <= code <= 191471)
        ):
            return True
    return False


def read_text_maybe(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252")
    for enc in encodings:
        try:
            return path.read_text(encoding=enc, errors="strict")
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def unique_destination(dst_dir: Path, name: str) -> Path:
    dst_path = dst_dir / name
    if not dst_path.exists():
        return dst_path
    base = dst_path.stem
    ext = dst_path.suffix
    i = 1
    while True:
        candidate = dst_dir / f"{base}__{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def main() -> None:
    src_dir = Path.cwd() if len(sys.argv) < 2 else Path(sys.argv[1])
    src_dir = src_dir.resolve()
    subdir = (src_dir / TARGET_SUBDIR).resolve()
    subdir.mkdir(exist_ok=True)
    for path in src_dir.iterdir():
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved.is_relative_to(subdir):
            continue
        try:
            text = read_text_maybe(path)
        except Exception as e:
            print(f"Skipped (read error): {path.name} ({e})")
            continue
        if has_chinese_chars_in_text(text):
            dst_path = unique_destination(subdir, path.name)
            shutil.move(str(path), str(dst_path))
            print(f"Moved: {dst_path.relative_to(src_dir)}")


if __name__ == "__main__":
    raise SystemExit(main())
