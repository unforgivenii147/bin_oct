#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def get_package_files(pkgname: str) -> list[str]:
    try:
        result = subprocess.run(
            ["dpkg", "-L", pkgname],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        return lines
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        result = subprocess.run(
            ["rpm", "-ql", pkgname],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        return lines
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    print(f"Error: could not find package '{pkgname}' via dpkg or rpm.")
    sys.exit(1)


def copy_pkg_files(pkgname: str) -> None:
    dest_root = Path.home() / "tmp" / "deb" / pkgname
    dest_root.mkdir(parents=True, exist_ok=True)
    paths = get_package_files(pkgname)
    copied_count = 0
    skipped_count = 0
    for raw_path in paths:
        src = Path(raw_path)
        if not src.exists() or not src.is_file():
            skipped_count += 1
            continue
        relative_path = src.relative_to(src.anchor)
        dest_path = dest_root / relative_path
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_path)
            copied_count += 1
        except (PermissionError, OSError) as e:
            print(f"Warning: could not copy '{src}': {e}")
            skipped_count += 1
    print(f"\nDone. Package: {pkgname}")
    print(f"Destination:   {dest_root}")
    print(f"Copied files:  {copied_count}")
    print(f"Skipped:       {skipped_count} (missing or non-file entries)")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python copy_pkg_files.py <pkgname>")
        sys.exit(1)
    pkgname = sys.argv[1]
    copy_pkg_files(pkgname)


if __name__ == "__main__":
    main()
