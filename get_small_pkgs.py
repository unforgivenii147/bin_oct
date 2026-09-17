#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import csv
import os
import site
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


def check_pure(dist_info_path) -> str | None:
    record_file = os.path.join(dist_info_path, "RECORD")
    pkg_name = Path(dist_info_path).name.replace(".dist-info", "").split("-")[0].lower()
    sum = 0
    if Path(record_file).exists():
        with Path(record_file).open(encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row[-1] and isinstance(int(row[-1]), int):
                    sum += int(row[-1])
    if sum < 1024 * 1024:
        return pkg_name
    return None


def get_pure() -> None:
    dist_info_dirs = get_all_dist_info_dirs()
    purz = []
    for ddir in dist_info_dirs:
        ispure = check_pure(ddir)
        if ispure:
            print(ispure)
            purz.append(ispure)
    with Path("/sdcard/data/pure").open("w", encoding="utf-8") as f:
        f.writelines(f"{k}\n" for k in purz)
    print(len(purz))


if __name__ == "__main__":
    get_pure()
