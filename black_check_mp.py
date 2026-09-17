#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ERROR_DIR = Path("error")
OK_DIR = Path("ok")


def ensure_dirs() -> None:
    ERROR_DIR.mkdir(exist_ok=True)
    OK_DIR.mkdir(exist_ok=True)


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 1
    while True:
        new_dest = parent / f"{stem}_{counter}{suffix}"
        if not new_dest.exists():
            return new_dest
        counter += 1


def black_check(path: Path) -> tuple[Path, bool]:
    print(f"[OK] {path}")
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return path, True
    except:
        return path, False


def collect_python_files() -> list[Path]:
    current_script = Path(__file__).resolve()
    files = []
    for file in Path().rglob("*.py"):
        resolved = file.resolve()
        if resolved == current_script:
            continue
        if ERROR_DIR in resolved.parents or OK_DIR in resolved.parents:
            continue
        files.append(file)
    return files


def main() -> None:
    ensure_dirs()
    files = collect_python_files()
    if not files:
        print("No python files found.")
        return
    print(f"Found {len(files)} python files.")
    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(black_check, f) for f in files]
        results.extend(future.result() for future in as_completed(futures))
    for path, passed in results:
        target_dir = OK_DIR if passed else ERROR_DIR
        dest = unique_destination(target_dir / path.name)
        shutil.move(str(path), str(dest))
        status = "OK" if passed else "ERROR"
        print(f"{status:6} → {path} → {dest}")


if __name__ == "__main__":
    raise SystemExit(main())
