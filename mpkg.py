#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

from loguru import logger


def find_dist_info_dir(site_packages: Path, pkg_name: str) -> Path:
    candidates = list(site_packages.glob(f"{pkg_name}-*.dist-info"))
    if not candidates:
        norm = pkg_name.replace("-", "_")
        candidates = list(site_packages.glob(f"{norm}-*.dist-info"))
    if not candidates:
        raise FileNotFoundError(msg)
    if len(candidates) > 1:
        logger.warning(
            "Multiple dist-info directories found for '{}', using: {}",
            pkg_name,
            candidates[0],
        )
    return candidates[0]


def copy_package_files(pkg_name: str, site_packages: Path) -> None:
    dist_info_dir = find_dist_info_dir(site_packages, pkg_name)
    record_path = dist_info_dir / "RECORD"
    if not record_path.is_file():
        print(f"RECORD file not found: {record_path}")
    dest_root = Path.home() / "tmp" / "1" / pkg_name
    dest_root.mkdir(parents=True, exist_ok=True)
    print("Destination root: {}", dest_root)
    missing_count = copied_count = error_count = 0
    with record_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            try:
                if not row:
                    continue
                rel_path = row[0]
                if not rel_path:
                    continue
                src_path = site_packages / rel_path
                if not src_path.exists() and "dist-info" in str(src_path):
                    missing_count += 1
                    continue
                if not src_path.exists() and src_path.suffix != ".pyc":
                    logger.warning("Missing file listed in RECORD: {}", src_path)
                    missing_count += 1
                    continue
                if not src_path.exists():
                    continue
                dest_path = dest_root / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(src_path, dest_path)
                copied_count += 1
            except Exception as e:
                logger.exception("Error while processing RECORD entry {}: {}", row, e)
                error_count += 1
    print("Missing files (warned): {}", missing_count)
    print("Copied: {} | Errors: {}", copied_count, error_count)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy (or move) package files based on RECORD metadata."
    )
    parser.add_argument("pkg", nargs="?", help="Package name to process")
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Process all packages in current directory",
    )
    args = parser.parse_args()
    if not args.pkg and not args.all:
        parser.error("You must specify a package name or use --all")
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{level}</green>|{message}")
    site_packages = Path.cwd()
    try:
        if args.all:
            dist_infos = list(site_packages.glob("*.dist-info"))
            if not dist_infos:
                logger.error("No .dist-info directories found in {}", site_packages)
                sys.exit(1)
            for dist_dir in dist_infos:
                pkg_name = dist_dir.stem.split("-")[0]
                print("Processing package: {}", pkg_name)
                try:
                    copy_package_files(pkg_name, site_packages)
                except Exception:
                    logger.exception("Failed to copy package {}", pkg_name)
                    continue
        else:
            copy_package_files(args.pkg, site_packages)
    except Exception as e:
        logger.exception("Fatal error: {}", e)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
