#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def find_site_packages() -> list[str]:
    import site

    site_packages = site.getsitepackages()
    valid_paths = [p for p in site_packages if p is not None]
    if not valid_paths:
        user_site = site.getusersitepackages()
        if user_site and Path(user_site).exists():
            valid_paths = [user_site]
    return valid_paths


def update_record_file(record_path: Path) -> bool:
    try:
        with record_path.open(encoding="utf-8") as f:
            lines = list(csv.reader(f))
        original_count = len(lines)
        filtered_lines = []
        for row in lines:
            if not row:
                continue
            path = row[0] if row else ""
            if (
                path.endswith(".pyc")
                or path in {"direct_url.json", "INSTALLER"}
                or path.startswith("LICENSE")
            ):
                continue
            filtered_lines.append(row)
        if len(filtered_lines) == original_count:
            return False
        with record_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(filtered_lines)
        print(
            f"  Updated: {record_path} (removed {original_count - len(filtered_lines)} entries)"
        )
        return True
    except Exception as e:
        print(f"  Error processing {record_path}: {e}", file=sys.stderr)
        return False


def scan_and_update(site_packages_dirs) -> tuple[int, int]:
    total_updated = 0
    total_files = 0
    for site_dir in site_packages_dirs:
        if not Path(site_dir).exists():
            print(f"Directory does not exist: {site_dir}")
            continue
        print(f"\nScanning: {site_dir}")
        for path in Path(site_dir).rglob("*"):
            if path.name == "RECORD" and update_record_file(path):
                total_updated += 1
    return total_files, total_updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove .pyc and direct_url.json references from RECORD files in site-packages"
    )
    parser.add_argument(
        "--site-dir",
        "-s",
        action="append",
        help="Specific site-packages directory to scan (can be used multiple times)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Print more detailed information"
    )
    args = parser.parse_args()
    site_dirs = args.site_dir or find_site_packages()
    if not site_dirs:
        print("Error: Could not find site-packages directory", file=sys.stderr)
        sys.exit(1)
    print(f"Python version: {sys.version}")
    print(f"Site packages directories: {', '.join(site_dirs)}")
    total_files, total_updated = scan_and_update(site_dirs)
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Total RECORD files found: {total_files}")
    print(f"  Files that would be/are updated: {total_updated}")


if __name__ == "__main__":
    raise SystemExit(main())
