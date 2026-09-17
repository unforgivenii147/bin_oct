#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import zipfile
from pathlib import Path


def is_empty_wheel(whl_path: Path) -> bool | None:
    try:
        with zipfile.ZipFile(whl_path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith((".py", ".so", ".pyi")):
                    return False
    except zipfile.BadZipFile:
        print(f"Warning: {whl_path} is not a valid ZIP file. Skipping.")
        return False
    return True


def main() -> None:
    empty_wheels = []
    cwd = Path.cwd()
    target = cwd / "empty_wheels"
    for whl in cwd.rglob("*.whl"):
        if whl.is_file():
            is_empty = is_empty_wheel(whl)
            if is_empty:
                empty_wheels.append(whl)
    if empty_wheels:
        print(f"\nFound {len(empty_wheels)} empty wheel(s).")
        target.mkdir(exist_ok=True)
        for k in empty_wheels:
            print(k.relative_to(cwd))
            new_path = target / k.name
            k.rename(new_path)
    else:
        print("No empty wheels found.")


if __name__ == "__main__":
    raise SystemExit(main())
