#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import importlib.metadata
import json
import os
import site
import sysconfig
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

logger.remove()
log_path = Path.home() / "tmp" / "apps" / "orphan_files.log"
logger.add(log_path)


def process_single_dist(
    dist_info: tuple[str, str, list[str]],
) -> tuple[set[str], set[str]]:
    dist_name, dist_path, dist_files = dist_info
    files = set()
    dirs = set()
    try:
        dist_info_dir = Path(dist_path)
        if dist_files:
            for path in dist_files:
                full_path = Path(path)
                if full_path.is_absolute():
                    files.add(str(full_path.resolve()))
                else:
                    files.add(str((dist_info_dir.parent / path).resolve()))
        if dist_info_dir.exists():
            files.add(str(dist_info_dir.resolve()))
            dirs.add(str(dist_info_dir.resolve()))
            record_file = dist_info_dir / "RECORD"
            if record_file.exists():
                try:
                    import csv

                    with open(record_file, "r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if row:
                                path = row[0]
                                if not path.startswith(".."):
                                    full_path = (dist_info_dir.parent / path).resolve()
                                    files.add(str(full_path))
                except:
                    pass
            installed_files = dist_info_dir / "installed-files.txt"
            if installed_files.exists():
                try:
                    with open(installed_files, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                full_path = (dist_info_dir.parent / line).resolve()
                                files.add(str(full_path))
                except:
                    pass
        try:
            top_level_file = dist_info_dir / "top_level.txt"
            if top_level_file.exists():
                top_level = top_level_file.read_text(encoding="utf-8")
                for line in top_level.splitlines():
                    line = line.strip()
                    if line:
                        pkg_path = dist_info_dir.parent / line
                        if pkg_path.exists():
                            files.add(str(pkg_path.resolve()))
                            if pkg_path.is_dir():
                                for file in pkg_path.rglob("*"):
                                    if file.is_file():
                                        files.add(str(file.resolve()))
        except:
            pass
    except Exception as e:
        print(f"Warning: Could not process package {dist_name}: {e}")
    return files, dirs


def scan_directory_worker(args: tuple[str, set[str], set[str]]) -> list[str]:
    site_dir, package_files, package_dirs = args
    orphan_files = []
    if not Path(site_dir).exists():
        return orphan_files
    for root, dirs, files in os.walk(site_dir):
        root_path = Path(root)
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        try:
            root_resolved = str(root_path.resolve())
            if root_resolved in package_dirs:
                dirs.clear()
                continue
        except:
            pass
        for file in files:
            path = str((root_path / file).resolve())
            if path in package_files:
                continue
            if should_skip_file(path):
                continue
            orphan_files.append(path)
    return orphan_files


def should_skip_file(path: str) -> bool:
    skip_patterns = [
        "__pycache__",
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".egg-link",
        ".pth",
        "easy-install.pth",
        "site.py",
    ]
    file_str = path.lower()
    for pattern in skip_patterns:
        if pattern in file_str:
            return True
    return bool(".dist-info" in file_str or ".egg-info" in file_str)


class OrphanFileDetector:
    def __init__(self):
        self.site_dirs = self._get_site_dirs()
        self.package_files: set[str] = set()
        self.package_dirs: set[str] = set()

    def _get_site_dirs(self) -> list[Path]:
        dirs = []
        for path in site.getsitepackages():
            if "user" not in path.lower():
                dirs.append(Path(path))
        try:
            site_packages = Path(sysconfig.get_paths()["purelib"])
            if site_packages not in dirs and "user" not in str(site_packages).lower():
                dirs.append(site_packages)
        except:
            pass
        return dirs

    def get_installed_packages(self) -> list[importlib.metadata.Distribution]:
        return list(importlib.metadata.distributions())

    def collect_package_files(self):
        print("Collecting package files...")
        packages = self.get_installed_packages()
        package_infos = []
        for dist in packages:
            try:
                dist_files = [str(f) for f in dist.files] if dist.files else []
                package_infos.append(
                    (dist.metadata["Name"], str(dist._path), dist_files)
                )
            except:
                continue
        with Pool(processes=8) as pool:
            results = pool.map(process_single_dist, package_infos)
        for files, dirs in results:
            self.package_files.update(files)
            self.package_dirs.update(dirs)
        print(f"Found {len(self.package_files)} files belonging to packages")

    def scan_site_dirs(self) -> list[Path]:
        orphan_files = []
        print("\nScanning site-packages directories:")
        scan_args = []
        for site_dir in self.site_dirs:
            print(f"  - {site_dir}")
            if site_dir.exists():
                scan_args.append((str(site_dir), self.package_files, self.package_dirs))
            else:
                print("    (does not exist)")
        with Pool(processes=8) as pool:
            results = pool.map(scan_directory_worker, scan_args)
        for files in results:
            orphan_files.extend(files)
        return sorted({Path(f) for f in orphan_files})

    def analyze_orphan_files(self, orphan_files: list[Path]):
        categories = {
            "Python packages/modules": [],
            "Data files": [],
            "Executables/scripts": [],
            "Libraries": [],
            "Other": [],
        }
        for path in orphan_files:
            ext = path.suffix.lower()
            name = path.name.lower()
            if ext in [".py", ".pyw"] or (
                path.is_dir()
                and "__init__.py" in [f.name for f in path.iterdir() if f.is_file()]
            ):
                categories["Python packages/modules"].append(path)
            elif ext in [
                ".txt",
                ".md",
                ".json",
                ".xml",
                ".csv",
                ".ini",
                ".cfg",
                ".yaml",
                ".yml",
                ".toml",
            ]:
                categories["Data files"].append(path)
            elif ext in [".exe", ".bat", ".cmd", ".sh", ".bash"] or (
                path.is_file() and os.access(path, os.X_OK)
            ):
                categories["Executables/scripts"].append(path)
            elif ext in [".so", ".dll", ".dylib", ".a", ".lib"]:
                categories["Libraries"].append(path)
            else:
                categories["Other"].append(path)
        return categories

    def run(self, verbose: bool = False):
        print("=" * 40)
        print("Orphan File Detector for Python Site-Packages")
        print("=" * 40)
        self.collect_package_files()
        orphan_files = self.scan_site_dirs()
        categories = self.analyze_orphan_files(orphan_files)
        print("\n" + "=" * 40)
        print("RESULTS")
        print("=" * 40)
        print(f"\nFound {len(orphan_files)} orphan files/directories:")
        for category, files in categories.items():
            if files:
                print(f"\n{category} ({len(files)}):")
                for path in sorted(files):
                    if verbose:
                        if path.is_file():
                            size = path.stat().st_size
                            size_str = self._format_size(size)
                            print(f"  {path} ({size_str})")
                        else:
                            print(f"  {path} (directory)")
                    else:
                        print(f"  {path}")
        print("\n" + "-" * 40)
        print("SUMMARY:")
        for category, files in categories.items():
            if files:
                print(f"  {category}: {len(files)}")
        print("\nWARNING: Review these files carefully before removing them.")
        print("Some may be intentionally installed or required by other tools.")
        return orphan_files

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def export_to_file(
        self, orphan_files: list[Path], output_file: str = "orphan_files.json"
    ):
        data = {
            "total_orphan_files": len(orphan_files),
            "site_directories": [str(d) for d in self.site_dirs],
            "files": [str(f) for f in orphan_files],
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"\nOrphan files list exported to: {output_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect orphan files in Python site-packages directories"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose output with file sizes",
    )
    parser.add_argument(
        "-e", "--export", action="store_true", help="Export results to JSON file"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="orphan_files.json",
        help="Output file for export (default: orphan_files.json)",
    )
    args = parser.parse_args()
    detector = OrphanFileDetector()
    orphan_files = detector.run(verbose=args.verbose)
    if args.export:
        detector.export_to_file(orphan_files, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
