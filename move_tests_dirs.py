#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dh import cprint

DRY_RUN = "-d" in sys.argv
EXCLUDED = ["numpy", "pandas", "scipy"]
SRC = Path.home() / ".local" / "lib" / "python3.12" / "site-packages"


def move_tests_folder(
    tests_path: Path, base_src: Path, base_dst: Path
) -> tuple[bool, str]:
    strp = str(tests_path)
    if "numpy" in strp or "scipy" in strp or "pandas" in strp or "numba" in strp:
        return False, f"excluded path"
    try:
        relative_path = tests_path.relative_to(base_src)
        parent_relative = relative_path.parent
        dst_path = base_dst / parent_relative / tests_path.name
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if DRY_RUN:
            cprint(f"will Move: {tests_path} -> {dst_path}")
            return True, f"Moved: {tests_path} -> {dst_path}"
        shutil.move(str(tests_path), str(dst_path))
        return True, f"Moved: {tests_path} -> {dst_path}"
    except Exception as e:
        return False, f"Error moving {tests_path}: {e}"


def move_tests_recursive(source_dir: str = SRC, max_workers: int = 4) -> int:
    source = Path(source_dir).resolve()
    destination = Path.home() / "tmp" / "tests_dirs"
    tests_folders = list(source.rglob("tests"))
    tests_folders = [p for p in tests_folders if p.is_dir()]
    if not tests_folders:
        print("No 'tests' folders found.")
        return 0
    print(f"Found {len(tests_folders)} 'tests' folder(s) to move")
    print(f"Source: {source}")
    print(f"Destination: {destination}")
    print()
    destination.parent.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                move_tests_folder, tests_path, source, destination
            ): tests_path
            for tests_path in tests_folders
        }
        for future in as_completed(futures):
            success, message = future.result()
            print(message)
            if success:
                moved_count += 1
    print()
    print(f"✓ Successfully moved {moved_count}/{len(tests_folders)} directories")
    return moved_count


if __name__ == "__main__":
    move_tests_recursive()
