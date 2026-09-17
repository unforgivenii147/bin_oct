#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that removes old versions of Python package metadata
files (.metadata) from a directory. The script parses package name and version
from each filename, groups by normalized package name, keeps only the highest
version, and removes (or backs up) the rest. It uses multiprocessing.Pool with
a fixed pool of 8 workers, loguru for logging, pathlib for paths, full type
hints, and argparse for a directory plus --dry-run and --backup-dir options.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path

from loguru import logger
from packaging.version import InvalidVersion, Version

# Module-level constants
WORKER_COUNT: int = 8
DEFAULT_BATCH_SIZE: int = 100
DEFAULT_VERSION: Version = Version("0.0.0")
FILENAME_PATTERN: re.Pattern[str] = re.compile(r"^(.+?)-(\d[\d._]*[a-zA-Z]*[\d]*)$")
NORMALIZE_PATTERN: re.Pattern[str] = re.compile(r"[-_.]+")

# Type aliases
VersionedPath = tuple[Version, Path]
PackageMap = dict[str, list[VersionedPath]]


def parse_filename(path: Path) -> tuple[str, Version, Path]:
    """Parse package name and version from a metadata filename.

    Args:
        path: Path to the metadata file.

    Returns:
        A tuple of (normalized-lowercase package name, parsed version, path).
    """
    name: str = path.stem
    match: re.Match[str] | None = FILENAME_PATTERN.match(name)
    if not match:
        logger.warning(f"Could not parse version from {path.name}")
        return (name.lower(), DEFAULT_VERSION, path)

    pkg_name: str = match.group(1)
    version_str: str = match.group(2)
    normalized_version: str = version_str.replace("_", ".")

    try:
        version: Version = Version(normalized_version)
    except InvalidVersion:
        logger.warning(f"Invalid version '{version_str}' in {path.name}")
        version = DEFAULT_VERSION

    return (pkg_name.lower(), version, path)


def normalize_package_name(name: str) -> str:
    """Normalize a package name to PEP 503 canonical form.

    Args:
        name: Raw package name.

    Returns:
        Normalized (lowercase, dash-separated) package name.
    """
    return NORMALIZE_PATTERN.sub("-", name).lower()


def find_metadata_files(directory: Path) -> list[Path]:
    """Find all .metadata files within a directory.

    Args:
        directory: Directory to scan.

    Returns:
        List of paths to .metadata files.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    return list(directory.glob("*.metadata"))


def process_file_batch(files: list[Path]) -> PackageMap:
    """Group a batch of metadata files by normalized package name.

    Args:
        files: Batch of metadata file paths.

    Returns:
        Mapping from normalized package name to list of (version, path).
    """
    packages: PackageMap = defaultdict(list)
    for path in files:
        pkg_name, version, path = parse_filename(path)
        normalized_name = normalize_package_name(pkg_name)
        packages[normalized_name].append((version, path))
    return dict(packages)


def find_old_versions(package_files: list[VersionedPath]) -> list[Path]:
    """Determine which versions to remove, keeping only the newest.

    Args:
        package_files: All (version, path) entries for one package.

    Returns:
        List of paths corresponding to older versions.
    """
    if len(package_files) <= 1:
        return []

    sorted_files: list[VersionedPath] = sorted(
        package_files, key=lambda x: x[0], reverse=True
    )
    latest: VersionedPath = sorted_files[0]
    old_versions: list[VersionedPath] = sorted_files[1:]

    print(f"  Keeping: {latest[1].name} (v{latest[0]})")
    for version, path in old_versions:
        print(f"  Removing: {path.name} (v{version})")

    return [path for _version, path in old_versions]


def merge_results(results: Iterable[PackageMap]) -> PackageMap:
    """Merge multiple package maps into one.

    Args:
        results: Iterable of per-batch package maps.

    Returns:
        Combined package map.
    """
    merged: PackageMap = defaultdict(list)
    for result in results:
        for pkg_name, versions in result.items():
            merged[pkg_name].extend(versions)
    return dict(merged)


def delete_files(
    paths: list[Path],
    dry_run: bool = True,
    backup_dir: Path | None = None,
) -> None:
    """Delete or back up a list of files.

    Args:
        paths: Files to remove.
        dry_run: If True, only log what would be done.
        backup_dir: If set, move files there instead of deleting.
    """
    for path in paths:
        if dry_run:
            print(f"  [DRY RUN] Would delete: {path.name}")
        elif backup_dir is not None:
            backup_path: Path = backup_dir / path.name
            shutil.move(str(path), str(backup_path))
            print(f"  Moved to backup: {path.name}")
        else:
            path.unlink()
            print(f"  Deleted: {path.name}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument vector (defaults to sys.argv[1:]).

    Returns:
        Parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(
        description="Remove old versions of Python package metadata files"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing metadata files (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        help="Move old files to backup directory instead of deleting",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of files to process per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the metadata cleanup script.

    Args:
        argv: Optional argument vector.

    Returns:
        Process exit code.
    """
    args: argparse.Namespace = parse_args(argv)

    metadata_dir: Path = Path(args.directory)
    if not metadata_dir.exists():
        logger.error(f"Directory '{metadata_dir}' does not exist")
        return 1

    backup_dir: Path | None = None
    if args.backup_dir:
        backup_dir = Path(args.backup_dir)
        if not args.dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning directory: {metadata_dir}")
    all_files: list[Path] = find_metadata_files(metadata_dir)
    print(f"Found {len(all_files)} metadata files")

    if not all_files:
        print("No metadata files found")
        return 0

    batch_size: int = max(1, args.batch_size)
    batches: list[list[Path]] = [
        all_files[i : i + batch_size] for i in range(0, len(all_files), batch_size)
    ]

    print(f"Processing {len(batches)} batches using {WORKER_COUNT} workers...")

    batch_results: list[PackageMap] = []
    with Pool(processes=WORKER_COUNT) as pool:
        async_results = [
            pool.apply_async(process_file_batch, (batch,)) for batch in batches
        ]
        for idx, async_result in enumerate(async_results):
            try:
                result: PackageMap = async_result.get()
                batch_results.append(result)
                print(f"  Batch {idx + 1}/{len(batches)} completed")
            except Exception as e:  # noqa: BLE001
                logger.exception(f"  Error processing batch {idx + 1}: {e}")

    print("Merging results...")
    all_packages: PackageMap = merge_results(batch_results)
    print(f"Processing {len(all_packages)} unique packages...")

    files_to_delete: list[Path] = []
    for pkg_name, versions in sorted(all_packages.items()):
        if len(versions) > 1:
            print(f"Package: {pkg_name} ({len(versions)} versions)")
            old_files: list[Path] = find_old_versions(versions)
            files_to_delete.extend(old_files)

    print("=" * 40)
    print("Summary:")
    print(f"  Total metadata files: {len(all_files)}")
    print(f"  Unique packages: {len(all_packages)}")
    print(f"  Files to remove: {len(files_to_delete)}")

    if files_to_delete:
        print("=" * 40)
        print(f"Removing {len(files_to_delete)} old version files...")
        delete_files(files_to_delete, dry_run=args.dry_run, backup_dir=backup_dir)
        if args.dry_run:
            print("This was a dry run. Use without --dry-run to actually delete files.")
    else:
        print("No duplicate versions found. All packages have single versions.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
