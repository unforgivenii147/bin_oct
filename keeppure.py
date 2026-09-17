#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import os
import site
from multiprocessing import cpu_count
from pathlib import Path


def get_all_dist_info_dirs():
    dist_info_dirs = []
    for site_dir in [*site.getsitepackages(), site.getusersitepackages()]:
        if Path(site_dir).exists():
            dist_info_dirs.extend(
                os.path.join(site_dir, item)
                for item in os.listdir(site_dir)
                if item.endswith(".dist-info")
            )
    return dist_info_dirs


def check_package_binary(dist_info_path) -> str | None:
    record_file = os.path.join(dist_info_path, "RECORD")
    pkg_name = Path(dist_info_path).name.replace(".dist-info", "").split("-")[0].lower()
    if Path(record_file).exists():
        try:
            with Path(record_file).open(encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and any(row[0].endswith(ext) for ext in [".so", ".pyd"]):
                        return pkg_name
        except:
            pass
    return None


def get_binary_packages_parallel():
    dist_info_dirs = get_all_dist_info_dirs()
    with Pool(processes=cpu_count()) as pool:
        results = pool.map(check_package_binary, dist_info_dirs)
    return {pkg for pkg in results if pkg}


def clean_requirements_txt(requirements_file: str = "requirements.txt") -> None:
    if not Path(requirements_file).exists():
        print(f"Error: {requirements_file} not found")
        return
    binary_packages = get_binary_packages_parallel()
    with Path("/sdcard/data/binary").open("w", encoding="utf-8") as fbin:
        fbin.write("\n".join(binary_packages))
        print("binary_pkgs created.")
    with Path(requirements_file).open(encoding="utf-8") as f:
        lines = [line.rstrip() for line in f]
    comments = [line for line in lines if line.startswith("#")]
    requirements = [line for line in lines if line and not line.startswith("#")]
    pure_python = []
    removed = []
    for req in requirements:
        pkg_name = (
            req.split("==")[0]
            .split(">=")[0]
            .split("<=")[0]
            .split("~=")[0]
            .strip()
            .lower()
        )
        if pkg_name in binary_packages:
            removed.append(req)
        else:
            pure_python.append(req)
    with Path(requirements_file).open("w", encoding="utf-8") as f:
        f.writelines(f"{comment}\n" for comment in comments)
        f.writelines(f"{pkg}\n" for pkg in sorted(pure_python))
    if removed:
        print(f"\n🗑️  Removed binary packages ({len(removed)}):")
        for pkg in sorted(removed):
            print(f"   - {pkg}")
    else:
        print("✅ No binary packages found in requirements.txt")


if __name__ == "__main__":
    import sys

    req_file = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    clean_requirements_txt(req_file)
