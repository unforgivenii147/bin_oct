#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import logging
import multiprocessing
import site
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def calculate_file_hash(path: Path) -> str:
    sha256_hash = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256_hash.update(chunk)
        raw_hash = sha256_hash.digest()
        b64_hash = base64.urlsafe_b64encode(raw_hash).decode("ascii").rstrip("=")
        return f"sha256={b64_hash}"
    except Exception:
        logger.exception("Error hashing %s", path)
        return ""


def get_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        logger.exception("Error getting size for %s", path)
        return 0


def parse_record_line(line: str) -> tuple[str, str, str]:
    parts = line.strip().split(",")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], "", ""


def should_include_file(path: Path) -> bool:
    name = path.name
    return not (
        path.suffix == ".pyc"
        or name.endswith(".pyc")
        or name in ("direct_url.json", "INSTALLER", "RECORD")
    )


def process_dist_info(dist_info_dir: Path) -> bool:
    record_path = dist_info_dir / "RECORD"
    print("Processing %s", record_path)
    if not record_path.exists():
        logger.error("RECORD not found: %s", record_path)
        return False
    try:
        with record_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        logger.exception("Failed to read %s", record_path)
        return False
    new_lines = []
    missing_files = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        relative_path, _old_hash, _old_size = parse_record_line(line)
        if relative_path == "RECORD":
            continue
        full_path = dist_info_dir.parent / relative_path
        if not should_include_file(full_path):
            logger.debug("Skipping excluded file: %s", relative_path)
            continue
        if not full_path.exists():
            missing_files.append(relative_path)
            logger.warning("Missing file: %s", relative_path)
            continue
        new_hash = calculate_file_hash(full_path)
        if not new_hash:
            logger.warning("Hash failed for %s, keeping original line", relative_path)
            new_lines.append(raw_line.rstrip("\n"))
            continue
        new_size = get_file_size(full_path)
        new_lines.append(f"{relative_path},{new_hash},{new_size}")
    record_relative = str(record_path.relative_to(dist_info_dir.parent))
    new_lines.append(f"{record_relative},,")
    if missing_files:
        logger.warning(
            "%d missing files in %s: %s",
            len(missing_files),
            dist_info_dir.name,
            ", ".join(missing_files),
        )
    try:
        record_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print("Updated %s", record_path)
    except Exception:
        logger.exception("Failed to write %s", record_path)
        return False
    try:
        record_hash = calculate_file_hash(record_path)
        record_size = get_file_size(record_path)
        with record_path.open("r", encoding="utf-8") as f:
            final_lines = f.readlines()
        if final_lines:
            last = final_lines[-1].strip().split(",")
            if len(last) >= 1:
                final_lines[-1] = f"{last[0]},{record_hash},{record_size}\n"
        record_path.write_text("".join(final_lines), encoding="utf-8")
        logger.debug("Self-hash updated for %s", record_path)
    except Exception:
        logger.exception("Failed to update self-hash for %s", record_path)
    return True


def main() -> None:
    site_packages = Path.cwd()
    dist_info_dirs = sorted(site_packages.glob("*.dist-info"))
    if not dist_info_dirs:
        logger.warning("you should run this script from a site packages folder.")
        sys.exit(0)
    print("Found %d distribution(s)", len(dist_info_dirs))
    updated = 0
    failed = 0
    with multiprocessing.Pool(processes=8) as pool:
        for success in pool.imap_unordered(process_dist_info, dist_info_dirs):
            if success:
                updated += 1
            else:
                failed += 1
    print(f"Summary: {updated} updated, {failed} failed")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
