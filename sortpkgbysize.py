#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def sort_packages_by_size(filename: str) -> None:
    with Path(filename).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    if "Installed-Size" not in fieldnames:
        print("Error: 'Installed-Size' column not found in CSV")
        return
    rows.sort(key=lambda x: int(x.get("Installed-Size") or 0), reverse=True)
    with Path(filename).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"File '{filename}' sorted by Installed-Size and overwritten.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sort Debian packages CSV by Installed-Size"
    )
    parser.add_argument("fname", help="CSV file to sort")
    args = parser.parse_args()
    sort_packages_by_size(args.fname)
