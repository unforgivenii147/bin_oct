#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import dict, list, tuple


def get_site_packages_dirs() -> list[Path]:
    site_dirs = []
    import site

    for path in site.getsitepackages():
        site_dirs.append(Path(path))
    user_site = site.getusersitepackages()
    if user_site:
        site_dirs.append(Path(user_site))
    common_paths = [
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        Path(sys.prefix)
        / "local"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
    ]
    for path in common_paths:
        if path.exists() and path not in site_dirs:
            site_dirs.append(path)
    return [d for d in site_dirs if d.exists() and d.is_dir()]


def get_package_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".dist-info"):
        name = name[:-10]
    elif name.endswith(".egg-info"):
        name = name[:-9]
    name = re.sub(r"-\d+\.\d+\.\d+.*$", "", name)
    name = re.sub(r"-\d+\.\d+.*$", "", name)
    name = re.sub(r"-py\d+\.\d+$", "", name)
    name = re.sub(r"-py\d+$", "", name)
    return name


def is_pure_python_package(pkg_name: str, site_dir: Path) -> bool:
    try:
        dist_info_patterns = [
            f"{pkg_name}*.dist-info",
            f"{pkg_name.replace('-', '_')}*.dist-info",
            f"{pkg_name.replace('_', '-')}*.dist-info",
        ]
        for pattern in dist_info_patterns:
            for dist_info in site_dir.glob(pattern):
                if dist_info.is_dir():
                    record_file = dist_info / "RECORD"
                    if record_file.exists():
                        try:
                            content = record_file.read_text(
                                encoding="utf-8", errors="ignore"
                            )
                            if ".so" in content:
                                return False
                        except Exception:
                            pass
        egg_info_patterns = [
            f"{pkg_name}*.egg-info",
            f"{pkg_name.replace('-', '_')}*.egg-info",
            f"{pkg_name.replace('_', '-')}*.egg-info",
        ]
        for pattern in egg_info_patterns:
            for egg_info in site_dir.glob(pattern):
                if egg_info.is_dir():
                    sources_file = egg_info / "SOURCES.txt"
                    if sources_file.exists():
                        try:
                            content = sources_file.read_text(
                                encoding="utf-8", errors="ignore"
                            )
                            if ".so" in content:
                                return False
                        except:
                            pass
                    native_libs = egg_info / "native_libs.txt"
                    if native_libs.exists():
                        return False
        package_dir_patterns = [
            pkg_name,
            pkg_name.replace("-", "_"),
            pkg_name.replace("_", "-"),
        ]
        for pattern in package_dir_patterns:
            for package_dir in site_dir.glob(pattern):
                if (
                    package_dir.is_dir()
                    and not package_dir.name.endswith(".dist-info")
                    and not package_dir.name.endswith(".egg-info")
                ):
                    for item in package_dir.rglob("*"):
                        if item.is_file() and item.suffix == ".so":
                            return False
                        if (
                            item.is_file()
                            and ".cpython-" in str(item)
                            and item.suffix == ".so"
                        ):
                            return False
        return True
    except Exception:
        return True


def scan_package(package_path: Path, site_dir: Path) -> dict[str, any]:
    pkg_name = get_package_name_from_path(package_path)
    result = {
        "name": pkg_name,
        "has_entry_points": False,
        "is_pure_python": True,
        "error": None,
    }
    try:
        has_entry_points = False
        dist_info_patterns = [
            f"{pkg_name}*.dist-info",
            f"{pkg_name.replace('-', '_')}*.dist-info",
            f"{pkg_name.replace('_', '-')}*.dist-info",
            f"{package_path.name}*.dist-info",
        ]
        for pattern in dist_info_patterns:
            for dist_info in site_dir.glob(pattern):
                if dist_info.is_dir():
                    entry_points = dist_info / "entry_points.txt"
                    if entry_points.exists():
                        has_entry_points = True
                        break
            if has_entry_points:
                break
        if not has_entry_points:
            egg_info_patterns = [
                f"{pkg_name}*.egg-info",
                f"{pkg_name.replace('-', '_')}*.egg-info",
                f"{pkg_name.replace('_', '-')}*.egg-info",
                f"{package_path.name}*.egg-info",
            ]
            for pattern in egg_info_patterns:
                for egg_info in site_dir.glob(pattern):
                    if egg_info.is_dir():
                        entry_points = egg_info / "entry_points.txt"
                        if entry_points.exists():
                            has_entry_points = True
                            break
                if has_entry_points:
                    break
        if not has_entry_points and package_path.is_dir():
            entry_points = package_path / "entry_points.txt"
            if entry_points.exists():
                has_entry_points = True
        result["has_entry_points"] = has_entry_points
        if not has_entry_points:
            result["is_pure_python"] = is_pure_python_package(pkg_name, site_dir)
    except Exception as e:
        result["error"] = str(e)
    return result


def find_packages_without_entry_points(site_dir: Path) -> tuple[list[str], list[str]]:
    pure_packages = []
    non_pure_packages = []
    processed_packages = set()
    try:
        items_to_scan = []
        for item in site_dir.iterdir():
            if item.is_dir():
                if item.name.startswith("_") or item.name.startswith("."):
                    continue
                init_file = item / "__init__.py"
                is_package_dir = init_file.exists()
                is_metadata = item.suffix in [".dist-info", ".egg-info"]
                if is_package_dir or is_metadata:
                    items_to_scan.append(item)
        for item in items_to_scan:
            result = scan_package(item, site_dir)
            if result["error"] is None and not result["has_entry_points"]:
                pkg_name = result["name"]
                if pkg_name in processed_packages:
                    continue
                processed_packages.add(pkg_name)
                if result["is_pure_python"]:
                    pure_packages.append(pkg_name)
                else:
                    non_pure_packages.append(pkg_name)
            elif result["error"]:
                print(f"Error scanning {item}: {result['error']}", file=sys.stderr)
    except Exception as e:
        print(f"Error scanning directory {site_dir}: {e}", file=sys.stderr)
    return pure_packages, non_pure_packages


def main():
    parser = argparse.ArgumentParser(
        description="Find Python packages without entry_points.txt in system site directories (Linux/Termux optimized)"
    )
    parser.add_argument(
        "--pure-output",
        default="noep_pure.txt",
        help="Output file for pure Python packages (default: noep_pure.txt)",
    )
    parser.add_argument(
        "--nonpure-output",
        default="noep_nopure.txt",
        help="Output file for non-pure packages (default: noep_nopure.txt)",
    )
    parser.add_argument(
        "-j", "--json", action="store_true", help="Output in JSON format"
    )
    parser.add_argument(
        "-p",
        "--processes",
        type=int,
        default=None,
        help=f"Number of processes to use (default: {cpu_count()})",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print verbose output"
    )
    args = parser.parse_args()
    site_dirs = get_site_packages_dirs()
    if not site_dirs:
        print("No site-packages directories found!", file=sys.stderr)
        sys.exit(1)
    if args.verbose:
        print(f"Found site directories: {[str(d) for d in site_dirs]}")
        print(f"Python version: {sys.version}")
        print(f"Platform: {sys.platform}")
    num_processes = args.processes or cpu_count()
    if args.verbose:
        print(f"Using {num_processes} processes")
    all_pure_packages = []
    all_nonpure_packages = []
    with Pool(processes=num_processes) as pool:
        results = pool.map(find_packages_without_entry_points, site_dirs)
        for pure_pkgs, nonpure_pkgs in results:
            all_pure_packages.extend(pure_pkgs)
            all_nonpure_packages.extend(nonpure_pkgs)
    seen_pure = set()
    unique_pure = []
    for pkg in all_pure_packages:
        if pkg not in seen_pure:
            seen_pure.add(pkg)
            unique_pure.append(pkg)
    seen_nonpure = set()
    unique_nonpure = []
    for pkg in all_nonpure_packages:
        if pkg not in seen_nonpure:
            seen_nonpure.add(pkg)
            unique_nonpure.append(pkg)
    unique_pure.sort()
    unique_nonpure.sort()
    if args.json:
        pure_data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_pure),
            "packages": unique_pure,
        }
        Path(args.pure_output).write_text(json.dumps(pure_data, indent=2))
    else:
        Path(args.pure_output).write_text("\n".join(unique_pure))
    if args.json:
        nonpure_data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_nonpure),
            "packages": unique_nonpure,
        }
        Path(args.nonpure_output).write_text(json.dumps(nonpure_data, indent=2))
    else:
        Path(args.nonpure_output).write_text("\n".join(unique_nonpure))
    print("=== SUMMARY ===")
    print(f"Platform: {sys.platform}")
    print(f"Pure Python packages without entry_points.txt: {len(unique_pure)}")
    print(f"Non-pure packages without entry_points.txt: {len(unique_nonpure)}")
    print(f"Total: {len(unique_pure) + len(unique_nonpure)}")
    if args.verbose:
        print(f"\nPure packages written to: {args.pure_output}")
        print(f"Non-pure packages written to: {args.nonpure_output}")
        if unique_pure:
            print("\nPure packages:")
            for pkg in unique_pure[:10]:
                print(f"  {pkg}")
            if len(unique_pure) > 10:
                print(f"  ... and {len(unique_pure) - 10} more")
        if unique_nonpure:
            print("\nNon-pure packages:")
            for pkg in unique_nonpure[:10]:
                print(f"  {pkg}")
            if len(unique_nonpure) > 10:
                print(f"  ... and {len(unique_nonpure) - 10} more")


if __name__ == "__main__":
    raise SystemExit(main())
