#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rapidfuzz import fuzz

PIP_LIST_FILE = "/sdcard/data/pip.list"


def create_pip_list_again() -> list[str]:
    installed = get_ipkgs()
    content = "\n".join(installed)
    Path(PIP_LIST_FILE).write_text(content, encoding="utf-8")
    return installed


def load_installed_packages() -> list[str]:
    path = Path(PIP_LIST_FILE)
    if get_file_age(path) > 1.0 or not path.exists():
        return create_pip_list_again()
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def find_dist_info(prefix):
    import site

    matches = []
    for sp in site.getsitepackages():
        sp_path = Path(sp)
        for d in sp_path.glob(f"{prefix}*.dist-info"):
            matches.append(d)
    for sp in (site.getusersitepackages(),):
        sp_path = Path(sp)
        for d in sp_path.glob(f"{prefix}*.dist-info"):
            matches.append(d)
    return matches


def uninstall_packages(pkg_name: str) -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", pkg_name], check=True
        )
        print(f"Uninstalled {pkg_name}")
    except subprocess.CalledProcessError:
        print(f"Skipped {pkg_name} (not installed or error)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <package_prefix>")
        sys.exit(1)
    prefix = sys.argv[1].lower()
    installed = load_installed_packages()
    to_uninstall = [
        pkg.lower()
        for pkg in installed
        if prefix in pkg.lower() or fuzz.partial_ratio(prefix, pkg.lower()) > 95
    ]
    if not to_uninstall:
        print("no match found")
        sys.exit(0)
    for k in to_uninstall:
        ans = input(f"remove {k} --> ? (y/n)")
        if ans in {"y", "Y", "Yes", "yes", "YES", "OK", "ok"}:
            uninstall_packages(k)
