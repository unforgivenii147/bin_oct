#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sysconfig
from pathlib import Path


def clean_record_file(record_path: Path) -> None:
    lines = record_path.read_text(encoding="utf-8").splitlines()
    cleaned = [line for line in lines if ".pyc" not in line]
    cleaned = [line for line in cleaned if "licenses" not in line]
    cleaned = [line for line in cleaned if "license.md" not in line.lower()]
    cleaned = [line for line in cleaned if "license.txt" not in line.lower()]
    record_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    print(f"{record_path.name} in {record_path.parent.name} cleaned")


def remove_pyc_entries() -> None:
    site_packages = Path(sysconfig.get_paths()["purelib"])
    for dist_info in site_packages.glob("*.dist-info"):
        record = dist_info / "RECORD"
        if record.exists():
            clean_record_file(record)


if __name__ == "__main__":
    remove_pyc_entries()
    print("Removed .pyc references from all RECORD files.")
