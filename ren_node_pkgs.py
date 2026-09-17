#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def sanitize_pkg_name(name: str) -> str:
    name = name.lstrip("@")
    name = name.replace("/", "__")
    return re.sub(r"[^\w.-]", "_", name)


def rename_package_dirs(cwd: Path, dry_run: bool = False) -> None:
    for pkg_json in cwd.rglob("package.json"):
        pkg_dir = pkg_json.parent
        if pkg_dir.name != "package":
            continue
        try:
            with pkg_json.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        pkg_name = data.get("name")
        if not pkg_name:
            continue
        new_name = sanitize_pkg_name(pkg_name)
        new_dir = pkg_dir.parent / new_name
        if pkg_dir.name == new_name:
            continue
        if new_dir.exists():
            print(f"[SKIP] {new_dir} already exists")
            continue
        if dry_run:
            print(f"[DRY] {pkg_dir} -> {new_dir}")
        else:
            print(f"[RENAME] {pkg_dir} -> {new_dir}")
            pkg_dir.rename(new_dir)


def main() -> None:
    cwd = Path.cwd()
    dry_run = "--dry-run" in sys.argv
    rename_package_dirs(cwd, dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
