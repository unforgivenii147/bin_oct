#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that scans installed Python packages for entry points, copies their files (excluding
bytecode and dist-info) into ~/tmp/packages/<package>, and processes them concurrently with a fixed
multiprocessing.Pool of 8 workers. Use loguru for logging, pathlib for paths, and complete type hints.
"""

import contextlib
import csv
import shutil
import site
import sys
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger

# Module-level constants
MAX_WORKERS: int = 8
DEST_ROOT: Path = Path.home() / "tmp" / "packages"


def get_python_paths() -> list[Path]:
    """Return existing Python search paths from site, user site, and PYTHONPATH."""
    import os

    paths: list[Path] = []
    paths.extend(Path(p) for p in site.getsitepackages())
    user_site = site.getusersitepackages()
    if user_site:
        paths.append(Path(user_site))
    pythonpath = os.environ.get("PYTHONPATH", "")
    if pythonpath:
        paths.extend(Path(p) for p in pythonpath.split(os.pathsep) if p)
    return [p for p in paths if p.exists()]


def find_dist_info_dirs(search_paths: list[Path]) -> list[Path]:
    """Find all .dist-info directories under the given search paths."""
    dist_info_dirs: list[Path] = []
    for path in search_paths:
        if not path.exists():
            continue
        print(f"Searching in {path}")
        dist_info_dirs.extend(path.glob("*.dist-info"))
    print(f"Found {len(dist_info_dirs)} dist-info directories")
    return dist_info_dirs


def has_entry_points(dist_info_dir: Path) -> bool:
    """Return True if the dist-info directory appears to declare entry points."""
    entry_points_file = dist_info_dir / "entry_points.txt"
    if entry_points_file.exists():
        return True
    metadata_file = dist_info_dir / "METADATA"
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                content = f.read()
                if "entry_points" in content.lower():
                    return True
        except Exception as e:
            logger.debug(f"Error reading {metadata_file}: {e}")
    return bool(
        (dist_info_dir / "top_level.txt").exists()
        and any(dist_info_dir.glob("scripts*"))
    )


def parse_record_file(dist_info_dir: Path) -> list[tuple[Path, str]]:
    """Parse a RECORD file and return (relative path, hash) pairs, skipping bytecode."""
    record_file = dist_info_dir / "RECORD"
    if not record_file.exists():
        logger.warning(f"No RECORD file found in {dist_info_dir}")
        return []
    files: list[tuple[Path, str]] = []
    try:
        with open(record_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row and len(row) >= 1:
                    relative_path = row[0]
                    hash_digest = row[1] if len(row) > 1 else ""
                    if (
                        not relative_path.endswith(".pyc")
                        and "__pycache__" not in relative_path
                    ):
                        files.append((Path(relative_path), hash_digest))
    except Exception as e:
        logger.error(f"Error parsing RECORD file {record_file}: {e}")
    return files


@lru_cache(maxsize=128)
def find_file_in_paths(
    relative_path: str, search_paths: tuple[Path, ...]
) -> Path | None:
    """Locate a file from a RECORD entry within the given search paths."""
    if Path(relative_path).is_absolute():
        abs_path = Path(relative_path)
        return abs_path if abs_path.exists() else None
    if ".data/" in relative_path:
        parts = relative_path.split(".data/", 1)
        data_subpath = parts[1] if len(parts) > 1 else relative_path
        data_mappings = {
            "purelib/": lambda p: p,
            "platlib/": lambda p: p,
            "headers/": lambda p: p,
            "scripts/": lambda p: p,
            "data/": lambda p: p,
        }
        for prefix in data_mappings:
            if data_subpath.startswith(prefix):
                subpath = data_subpath[len(prefix) :]
                for base_path in search_paths:
                    candidate = base_path / subpath
                    if candidate.exists():
                        return candidate
                break
    for base_path in search_paths:
        candidate = base_path / relative_path
        if candidate.exists():
            return candidate
    candidate = Path(relative_path)
    if candidate.exists():
        return candidate
    return None


def copy_package_files(
    package_info: tuple[str, Path, list[str]],
) -> tuple[str, bool, str]:
    """Copy all files listed in a package's RECORD into its destination directory."""
    package_name, dist_info_dir, search_paths = package_info
    try:
        dest_base = DEST_ROOT / package_name
        dest_base.parent.mkdir(parents=True, exist_ok=True)
        record_files = parse_record_file(dist_info_dir)
        if not record_files:
            return (package_name, False, "No files in RECORD")
        search_paths_tuple = tuple(Path(p) for p in search_paths)
        files_copied = 0
        for relative_path, _ in record_files:
            if ".dist-info" in str(relative_path):
                continue
            source_path = find_file_in_paths(str(relative_path), search_paths_tuple)
            if source_path is None:
                logger.debug(f"Could not find: {relative_path}")
                continue
            dest_path = dest_base
            relative_str = str(relative_path)
            if relative_path.is_absolute():
                dest_path = dest_base / relative_path.name
            else:
                parts = Path(relative_str).parts
                clean_parts = [p for p in parts if p not in ("..", ".")]
                if clean_parts:
                    dest_path = dest_base / Path(*clean_parts)
                else:
                    dest_path = dest_base / Path(relative_str).name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if source_path.is_file():
                    shutil.copy2(source_path, dest_path)
                    files_copied += 1
                elif source_path.is_dir():
                    if not dest_path.exists():
                        shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                        files_copied += 1
            except Exception as e:
                logger.debug(f"Error copying {source_path}: {e}")
        dist_info_dest = dest_base / dist_info_dir.name
        if dist_info_dir.exists() and not dist_info_dest.exists():
            with contextlib.suppress(Exception):
                shutil.copytree(dist_info_dir, dist_info_dest, dirs_exist_ok=True)
        success_msg = f"Copied {files_copied} files"
        print(f"{package_name}: {success_msg}")
        return (package_name, True, success_msg)
    except Exception as e:
        error_msg = f"Error: {e!s}"
        logger.error(f"{package_name}: {error_msg}")
        return (package_name, False, error_msg)


def main() -> int:
    """Entry point: discover, copy, and summarize packages with entry points."""
    print("Starting package copy process...")
    search_paths = get_python_paths()
    print(f"Search paths: {search_paths}")
    dist_info_dirs = find_dist_info_dirs(search_paths)
    if not dist_info_dirs:
        logger.error("No dist-info directories found!")
        return 1

    packages_with_entry_points: list[tuple[str, Path]] = []
    for dist_info_dir in dist_info_dirs:
        if has_entry_points(dist_info_dir):
            package_name = dist_info_dir.name.replace(".dist-info", "")
            if "-" in package_name:
                print(f"Found package with entry points: {package_name}")
            packages_with_entry_points.append((package_name, dist_info_dir))

    print(f"Found {len(packages_with_entry_points)} packages with entry points")
    if not packages_with_entry_points:
        logger.warning("No packages with entry points found!")
        return 1

    search_paths_str = [str(p) for p in search_paths]
    package_infos: list[tuple[str, Path, list[str]]] = [
        (name, d, search_paths_str) for name, d in packages_with_entry_points
    ]

    print(f"Processing {len(package_infos)} packages using {MAX_WORKERS} workers...")

    results: list[tuple[str, bool, str]] = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[Any] = [
            pool.apply_async(copy_package_files, (pkg_info,))
            for pkg_info in package_infos
        ]
        for async_result in async_results:
            try:
                result: tuple[str, bool, str] = async_result.get()
                results.append(result)
            except Exception as e:
                logger.error(f"Exception processing package: {e}")
                results.append(("unknown", False, str(e)))

    print("=" * 40)
    print("SUMMARY")
    print("-" * 40)

    successful = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]

    print(f"✅ Successfully processed: {len(successful)} packages")
    for pkg_name, _, msg in successful:
        print(f"  - {pkg_name}: {msg}")

    if failed:
        print(f"❌ Failed: {len(failed)} packages")
        for pkg_name, _, msg in failed:
            print(f"  - {pkg_name}: {msg}")

    print(f"📁 Packages copied to: {DEST_ROOT}")
    print("-" * 40)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
