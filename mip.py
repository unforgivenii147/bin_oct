#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import importlib.metadata
import sys
import zipfile
from pathlib import Path

from dh import get_files


def parse_version_tuple(version_str: str) -> tuple:
    try:
        return tuple(int(x) for x in version_str.split(".") if x.isdigit())
    except Exception:
        return (version_str,)


def get_files(directory: Path, ext: list[str]) -> list[Path]:
    return [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ext]


def get_installed_packages() -> dict[str, str]:
    return {
        dist.metadata["Name"].lower(): dist.version
        for dist in importlib.metadata.distributions()
    }


def get_wheel_package_info(path: Path) -> tuple[str, str] | tuple[None, None]:
    try:
        with zipfile.ZipFile(path, "r") as zip_ref:
            metadata_file = next(
                (f for f in zip_ref.namelist() if f.endswith("METADATA")), None
            )
            if metadata_file:
                pkg_name, pkg_version = None, None
                with zip_ref.open(metadata_file) as f:
                    for line in f:
                        line_str = line.decode("utf-8", errors="ignore")
                        if line_str.startswith("Name:"):
                            pkg_name = line_str.split(":", 1)[1].strip()
                        elif line_str.startswith("Version:"):
                            pkg_version = line_str.split(":", 1)[1].strip()
                        if pkg_name and pkg_version:
                            return pkg_name, pkg_version
    except Exception as e:
        print(f"Error reading {path.name}: {e}")
    return None, None


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".whl"])
    if not files:
        print("Run this script in a directory containing .whl files.")
        sys.exit(1)
    installed = get_installed_packages()
    for path in files:
        pkg_name, pkg_version = get_wheel_package_info(path)
        if pkg_name and pkg_version:
            installed_version = installed.get(pkg_name.lower())
            if installed_version:
                v_installed = parse_version_tuple(installed_version)
                v_wheel = parse_version_tuple(pkg_version)
                if v_installed == v_wheel:
                    print(
                        f"🗑️  {pkg_name} == {pkg_version} already installed, deleting {path.name}"
                    )
                    path.unlink()
                elif v_installed > v_wheel:
                    print(
                        f"🗑️  Installed version ({
                            installed_version
                        }) is newer than wheel ({pkg_version}), deleting {path.name}"
                    )
                    path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
