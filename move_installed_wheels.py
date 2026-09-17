#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from importlib import metadata
from pathlib import Path

from dh import cprint
from packaging.utils import parse_wheel_filename
from packaging.version import Version

WHL_DIR = Path("/sdcard/whl")
DEST_DIR = Path("/sdcard/installed")
DEST_DIR2 = Path("/sdcard/invalid")
if not DEST_DIR.exists():
    DEST_DIR.mkdir()
if not DEST_DIR2.exists():
    DEST_DIR2.mkdir()
EXCLUDED_PACKAGES = {
    "pybind11",
    "dh",
    "pip",
    "setuptools",
    "wheel",
    "packaging",
    "importlib_metadata",
    "importlib_resources",
    "pkginfo",
    "scikit_build_core",
    "setuptools_scm",
    "setuptools_rust",
}


def ensure_venv() -> None:
    if sys.prefix == sys.base_prefix:
        print("⚠ Not running inside a virtual environment.")
        sys.exit(1)


def get_installed_packages():
    installed = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        version = dist.version
        if name:
            installed[name.lower().replace("-", "_")] = Version(version)
    return installed


def normalize(name: str) -> str:
    return name.lower().replace("-", "_")


def main() -> None:
    if not WHL_DIR.exists():
        print(f"Directory not found: {WHL_DIR}")
        return
    installed_pkgs = get_installed_packages()
    moved = 0
    for wheel in WHL_DIR.rglob("*.whl"):
        try:
            dist_name, version, *_ = parse_wheel_filename(wheel.name)
            norm_name = normalize(dist_name)
            if norm_name in EXCLUDED_PACKAGES:
                print(f"[EXCLUDED] {dist_name}=={version} → skipped")
                continue
            if norm_name in installed_pkgs:
                installed_version = installed_pkgs[norm_name]
                if installed_version == Version(str(version)):
                    cprint(f"[MATCH] {dist_name}=={version} → removing", "cyan")
                    wheel.unlink()
                    moved += 1
                else:
                    wheel.unlink()
                    moved += 1
                    print(
                        f"[DIFF VERSION] {dist_name} (installed {installed_version}, wheel {version}) -> removed"
                    )
        except Exception as e:
            print(f"[ERROR] {wheel.name}: {e}")
            shutil.move(str(wheel), DEST_DIR2 / wheel.name)
    print(f"\nDone. Removed {moved} wheel(s).")


if __name__ == "__main__":
    raise SystemExit(main())
