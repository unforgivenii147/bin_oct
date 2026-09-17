#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import re
import shutil
import sysconfig
from pathlib import Path

from wheel.wheelfile import WheelFile


def find_site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def list_installed_packages(site: Path):
    pkgs = {}
    for item in site.iterdir():
        if item.name.endswith(".dist-info"):
            name_version = item.name[:-10]
            m = re.match(r"(.+)-([\w\.]+)", name_version)
            if not m:
                continue
            pkg, version = m.group(1), m.group(2)
            pkgs[pkg.lower()] = pkg, version
    return pkgs


def get_wheel_tags(dist_info: Path) -> list[str]:
    wheel_file = dist_info / "WHEEL"
    if not wheel_file.exists():
        return ["py3-none-any"]
    content = wheel_file.read_text()
    tags = [
        line.split(":", 1)[1].strip()
        for line in content.splitlines()
        if line.startswith("Tag:")
    ]
    return tags or ["py3-none-any"]


def copy_package_files(pkg: str, site: Path, dst: Path) -> None:
    candidates = [
        site / pkg,
        site / f"{pkg}.py",
        site / f"{pkg.replace('-', '_')}",
        site / f"{pkg.replace('-', '_')}.py",
    ]
    for c in candidates:
        if c.exists():
            if c.is_dir():
                shutil.copytree(c, dst / c.name)
            else:
                shutil.copy2(c, dst / c.name)
            break


def copy_dist_info(pkg: str, version: str, site: Path, dst: Path) -> Path:
    dist_dir = site / f"{pkg}-{version}.dist-info"
    out = dst / dist_dir.name
    shutil.copytree(dist_dir, out)
    return out


def copy_scripts(pkg: str, dst: Path) -> None:
    scripts_dir = Path(sysconfig.get_paths()["scripts"])
    if not scripts_dir.exists():
        return
    pattern = re.compile(f"^{pkg}(-.+)?$")
    for script in scripts_dir.iterdir():
        if script.is_file() and pattern.match(script.name):
            shutil.copy2(script, dst / script.name)


def build_wheel(pkg: str, version: str, tag: str, src_dir: Path, out_dir: Path) -> Path:
    wheel_name = f"{pkg}-{version}-{tag}.whl"
    wheel_path = out_dir / wheel_name
    with WheelFile(str(wheel_path), "w") as wf:
        for root, _dirs, files in os.walk(src_dir):
            for file in files:
                full = Path(root) / file
                arcname = full.relative_to(src_dir)
                wf.write(str(full), str(arcname))
    return wheel_path


def repack(pkg: str, site: Path, out_repack: Path, out_whl: Path) -> None:
    pkg_lower = pkg.lower()
    installed = list_installed_packages(site)
    if pkg_lower not in installed:
        print(f"Package '{pkg}' not found.")
        return
    real_pkg, version = installed[pkg_lower]
    target_dir = out_repack / real_pkg
    target_dir.mkdir(parents=True, exist_ok=True)
    copy_package_files(real_pkg, site, target_dir)
    dist_info = copy_dist_info(real_pkg, version, site, target_dir)
    copy_scripts(real_pkg, target_dir)
    tags = get_wheel_tags(dist_info)
    tag = tags[0]
    wheel = build_wheel(real_pkg, version, tag, target_dir, out_whl)
    print(f"Repacked: {real_pkg} → {wheel}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repack installed Python packages")
    parser.add_argument("packages", nargs="*", help="Package names")
    parser.add_argument(
        "-a", "--all", action="store_true", help="Repack all installed pkgs"
    )
    args = parser.parse_args()
    site = find_site_packages()
    out_repack = Path.home() / "tmp" / "repack"
    out_whl = Path.home() / "tmp" / "whl"
    out_repack.mkdir(parents=True, exist_ok=True)
    out_whl.mkdir(parents=True, exist_ok=True)
    if args.all:
        pkgs = list_installed_packages(site)
        for pkg, (real, _) in pkgs.items():
            repack(real, site, out_repack, out_whl)
    else:
        for pkg in args.packages:
            repack(pkg, site, out_repack, out_whl)


if __name__ == "__main__":
    raise SystemExit(main())
