#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def inspect_and_move_wheels(root_dir="."):
    root_path = Path(root_dir).resolve()
    target_dir = root_path / "suspicious"
    print(f"Scanning for .whl files recursively in: {root_path}\n")
    wheel_files = list(root_path.rglob("*.whl"))
    if not wheel_files:
        print("No .whl files found.")
        return
    bad_wheels_count = 0
    for whl_path in wheel_files:
        if target_dir in whl_path.parents:
            continue
        try:
            with zipfile.ZipFile(whl_path, "r") as archive:
                namelist = archive.namelist()
                loose_root_files = []
                for name in namelist:
                    if name.endswith("/"):
                        continue
                    if "/" not in name and name.endswith(
                        (".py", ".pyc", ".pyd", ".so", ".dll")
                    ):
                        loose_root_files.append(name)
                if loose_root_files:
                    bad_wheels_count += 1
                    relative_path = whl_path.relative_to(root_path)
                    print(f"❌ MISCONFIGURED WHEEL: {relative_path}")
                    print(f"   Dumps into site-packages root: {loose_root_files}")
                    target_dir.mkdir(exist_ok=True)
                    dest_path = target_dir / whl_path.name
                    if dest_path.exists():
                        dest_path = (
                            target_dir
                            / f"{whl_path.stem}_duplicate_{bad_wheels_count}{whl_path.suffix}"
                        )
                    shutil.move(str(whl_path), str(dest_path))
                    print(f"   ➡️ Moved to: {dest_path.relative_to(root_path)}")
                    print("-" * 40)
        except zipfile.BadZipFile:
            print(f"⚠️  Error: {whl_path.name} is a corrupt or invalid zip/wheel file.")
        except Exception as e:
            print(f"⚠️  Error processing {whl_path.name}: {e}")
    print(
        f"""
Scan complete. Moved {bad_wheels_count} misconfigured wheel(s) to './suspicious/' out of {len(wheel_files)} total checked."""
    )


if __name__ == "__main__":
    inspect_and_move_wheels()
