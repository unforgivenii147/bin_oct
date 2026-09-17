#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

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


def copy_package_files(pkg_name: str) -> None:
    site_packages = Path.cwd()
    dist_info_dir = find_dist_info_dir(site_packages, pkg_name)
    record_path = dist_info_dir / "RECORD"
    if not record_path.is_file():
        raise FileNotFoundError(msg)
    dest_root = Path.home() / "tmp" / "1" / pkg_name
    dest_root.mkdir(parents=True, exist_ok=True)
    print("Destination root: {}", dest_root)
    missing_count = 0
    copied_count = 0
    error_count = 0
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
                logger.debug("Copied {} -> {}", src_path, dest_path)
                copied_count += 1
            except Exception as e:
                logger.exception("Error while processing RECORD entry {}: {}", row, e)
                error_count += 1
    print("\nMissing files (ignored, warned): {}", missing_count)
    print("\nErrors: {}", error_count)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <package-name>", file=sys.stderr)
        sys.exit(1)
    pkg_name = sys.argv[1].strip()
    if not pkg_name:
        print("Package name must not be empty", file=sys.stderr)
        sys.exit(1)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{level}</green>|{message}")
    try:
        copy_package_files(pkg_name)
    except Exception as e:
        logger.exception("Fatal error while copying package '{}': {}", pkg_name, e)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
