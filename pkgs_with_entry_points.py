#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path


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


def parse_entry_points(entry_points_file: Path) -> dict[str, list[str]]:
    scripts = {"console_scripts": [], "gui_scripts": [], "other": []}
    try:
        if not entry_points_file.exists():
            return scripts
        content = entry_points_file.read_text(encoding="utf-8", errors="ignore")
        config = configparser.ConfigParser()
        try:
            config.read_string(content)
            if config.has_section("console_scripts"):
                for key, _value in config.items("console_scripts"):
                    scripts["console_scripts"].append(key)
            if config.has_section("gui_scripts"):
                for key, _value in config.items("gui_scripts"):
                    scripts["gui_scripts"].append(key)
            for section in config.sections():
                if section not in ["console_scripts", "gui_scripts"]:
                    for key, _value in config.items(section):
                        scripts["other"].append(f"{section}:{key}")
        except:
            lines = content.split("\n")
            current_section = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1]
                elif current_section and "=" in line:
                    key = line.split("=")[0].strip()
                    if current_section == "console_scripts":
                        scripts["console_scripts"].append(key)
                    elif current_section == "gui_scripts":
                        scripts["gui_scripts"].append(key)
                    else:
                        scripts["other"].append(f"{current_section}:{key}")
    except Exception:
        pass
    return scripts


def scan_package(package_path: Path, site_dir: Path) -> dict[str, any]:
    pkg_name = get_package_name_from_path(package_path)
    result = {
        "name": pkg_name,
        "has_entry_points": False,
        "entry_points_data": None,
        "is_pure_python": True,
        "error": None,
    }
    try:
        entry_points_file = None
        dist_info_patterns = [
            f"{pkg_name}*.dist-info",
            f"{pkg_name.replace('-', '_')}*.dist-info",
            f"{pkg_name.replace('_', '-')}*.dist-info",
            f"{package_path.name}*.dist-info",
        ]
        for pattern in dist_info_patterns:
            for dist_info in site_dir.glob(pattern):
                if dist_info.is_dir():
                    ep_file = dist_info / "entry_points.txt"
                    if ep_file.exists():
                        entry_points_file = ep_file
                        break
            if entry_points_file:
                break
        if not entry_points_file:
            egg_info_patterns = [
                f"{pkg_name}*.egg-info",
                f"{pkg_name.replace('-', '_')}*.egg-info",
                f"{pkg_name.replace('_', '-')}*.egg-info",
                f"{package_path.name}*.egg-info",
            ]
            for pattern in egg_info_patterns:
                for egg_info in site_dir.glob(pattern):
                    if egg_info.is_dir():
                        ep_file = egg_info / "entry_points.txt"
                        if ep_file.exists():
                            entry_points_file = ep_file
                            break
                if entry_points_file:
                    break
        if not entry_points_file and package_path.is_dir():
            ep_file = package_path / "entry_points.txt"
            if ep_file.exists():
                entry_points_file = ep_file
        if entry_points_file:
            result["has_entry_points"] = True
            result["entry_points_data"] = parse_entry_points(entry_points_file)
        result["is_pure_python"] = is_pure_python_package(pkg_name, site_dir)
    except Exception as e:
        result["error"] = str(e)
    return result


def find_packages_categorized(
    site_dir: Path,
) -> tuple[list[str], list[str], list[str], list[str]]:
    pure_without_ep = []
    nonpure_without_ep = []
    pure_with_ep = []
    nonpure_with_ep = []
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
            if result["error"] is None:
                pkg_name = result["name"]
                if pkg_name in processed_packages:
                    continue
                processed_packages.add(pkg_name)
                if result["has_entry_points"]:
                    if result["is_pure_python"]:
                        pure_with_ep.append(pkg_name)
                    else:
                        nonpure_with_ep.append(pkg_name)
                elif result["is_pure_python"]:
                    pure_without_ep.append(pkg_name)
                else:
                    nonpure_without_ep.append(pkg_name)
            elif result["error"]:
                print(f"Error scanning {item}: {result['error']}", file=sys.stderr)
    except Exception as e:
        print(f"Error scanning directory {site_dir}: {e}", file=sys.stderr)
    return pure_without_ep, nonpure_without_ep, pure_with_ep, nonpure_with_ep


def main():
    parser = argparse.ArgumentParser(
        description="Find Python packages and categorize by entry_points.txt and purity (Linux/Termux optimized)"
    )
    parser.add_argument(
        "--pure-noep-output",
        default="noep_pure.txt",
        help="Output file for pure Python packages without entry_points (default: noep_pure.txt)",
    )
    parser.add_argument(
        "--nonpure-noep-output",
        default="noep_nopure.txt",
        help="Output file for non-pure packages without entry_points (default: noep_nopure.txt)",
    )
    parser.add_argument(
        "--pure-ep-output",
        default="ep_pure.txt",
        help="Output file for pure Python packages with entry_points (default: ep_pure.txt)",
    )
    parser.add_argument(
        "--nonpure-ep-output",
        default="ep_nopure.txt",
        help="Output file for non-pure packages with entry_points (default: ep_nopure.txt)",
    )
    parser.add_argument(
        "--ep-details-output",
        default="ep_details.txt",
        help="Output file for detailed entry_points information (default: ep_details.txt)",
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
    all_pure_noep = []
    all_nonpure_noep = []
    all_pure_ep = []
    all_nonpure_ep = []
    with Pool(processes=num_processes) as pool:
        results = pool.map(find_packages_categorized, site_dirs)
        for pure_noep, nonpure_noep, pure_ep, nonpure_ep in results:
            all_pure_noep.extend(pure_noep)
            all_nonpure_noep.extend(nonpure_noep)
            all_pure_ep.extend(pure_ep)
            all_nonpure_ep.extend(nonpure_ep)

    def deduplicate(lst):
        seen = set()
        unique = []
        for item in lst:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    unique_pure_noep = deduplicate(all_pure_noep)
    unique_nonpure_noep = deduplicate(all_nonpure_noep)
    unique_pure_ep = deduplicate(all_pure_ep)
    unique_nonpure_ep = deduplicate(all_nonpure_ep)
    unique_pure_noep.sort()
    unique_nonpure_noep.sort()
    unique_pure_ep.sort()
    unique_nonpure_ep.sort()
    if args.json:
        data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_pure_noep),
            "packages": unique_pure_noep,
        }
        Path(args.pure_noep_output).write_text(json.dumps(data, indent=2))
    else:
        Path(args.pure_noep_output).write_text("\n".join(unique_pure_noep))
    if args.json:
        data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_nonpure_noep),
            "packages": unique_nonpure_noep,
        }
        Path(args.nonpure_noep_output).write_text(json.dumps(data, indent=2))
    else:
        Path(args.nonpure_noep_output).write_text("\n".join(unique_nonpure_noep))
    if args.json:
        data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_pure_ep),
            "packages": unique_pure_ep,
        }
        Path(args.pure_ep_output).write_text(json.dumps(data, indent=2))
    else:
        Path(args.pure_ep_output).write_text("\n".join(unique_pure_ep))
    if args.json:
        data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_nonpure_ep),
            "packages": unique_nonpure_ep,
        }
        Path(args.nonpure_ep_output).write_text(json.dumps(data, indent=2))
    else:
        Path(args.nonpure_ep_output).write_text("\n".join(unique_nonpure_ep))
    if args.verbose:
        print("\nGathering entry points details...")
    ep_details = []
    with Pool(processes=num_processes) as pool:
        results = pool.map(scan_for_entry_points, site_dirs)
        for details in results:
            ep_details.extend(details)
    seen_ep = set()
    unique_ep_details = []
    for pkg in ep_details:
        if pkg["name"] not in seen_ep:
            seen_ep.add(pkg["name"])
            unique_ep_details.append(pkg)
    unique_ep_details.sort(key=lambda x: x["name"])
    if args.json:
        data = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "platform": sys.platform,
            "total": len(unique_ep_details),
            "packages": unique_ep_details,
        }
        Path(args.ep_details_output).write_text(json.dumps(data, indent=2))
    else:
        lines = []
        for pkg in unique_ep_details:
            lines.append(f"{pkg['name']}:")
            if pkg["entry_points"]["console_scripts"]:
                lines.append(
                    f"  console_scripts: {', '.join(pkg['entry_points']['console_scripts'])}"
                )
            if pkg["entry_points"]["gui_scripts"]:
                lines.append(
                    f"  gui_scripts: {', '.join(pkg['entry_points']['gui_scripts'])}"
                )
            if pkg["entry_points"]["other"]:
                lines.append(f"  other: {', '.join(pkg['entry_points']['other'])}")
            lines.append("")
        Path(args.ep_details_output).write_text("\n".join(lines))
    print(f"\n{'=' * 40}")
    print("SUMMARY - Python Package Classification")
    print(f"{'=' * 40}")
    print(f"Platform: {sys.platform}")
    print(f"Site directories: {len(site_dirs)}")
    print()
    print("Without entry_points.txt:")
    print(f"  • Pure Python packages: {len(unique_pure_noep)}")
    print(f"  • Non-pure packages:    {len(unique_nonpure_noep)}")
    print(
        f"  • Subtotal:             {len(unique_pure_noep) + len(unique_nonpure_noep)}"
    )
    print()
    print("With entry_points.txt:")
    print(f"  • Pure Python packages: {len(unique_pure_ep)}")
    print(f"  • Non-pure packages:    {len(unique_nonpure_ep)}")
    print(f"  • Subtotal:             {len(unique_pure_ep) + len(unique_nonpure_ep)}")
    print()
    print(
        f"Grand total: {
            len(unique_pure_noep)
            + len(unique_nonpure_noep)
            + len(unique_pure_ep)
            + len(unique_nonpure_ep)
        }"
    )
    print(f"{'=' * 40}")
    if args.verbose:
        print("\nOutput files:")
        print(f"  Pure no-ep:      {args.pure_noep_output}")
        print(f"  Non-pure no-ep:  {args.nonpure_noep_output}")
        print(f"  Pure with ep:    {args.pure_ep_output}")
        print(f"  Non-pure with ep:{args.nonpure_ep_output}")
        print(f"  EP details:      {args.ep_details_output}")
        if unique_pure_noep:
            print("\nSample - Pure packages without EP (first 5):")
            for pkg in unique_pure_noep[:5]:
                print(f"  {pkg}")
            if len(unique_pure_noep) > 5:
                print(f"  ... and {len(unique_pure_noep) - 5} more")
        if unique_pure_ep:
            print("\nSample - Pure packages with EP (first 5):")
            for pkg in unique_pure_ep[:5]:
                print(f"  {pkg}")
            if len(unique_pure_ep) > 5:
                print(f"  ... and {len(unique_pure_ep) - 5} more")


def scan_for_entry_points(site_dir: Path) -> list[dict]:
    packages_with_ep = []
    processed = set()
    try:
        for item in site_dir.iterdir():
            if (
                not item.is_dir()
                or item.name.startswith("_")
                or item.name.startswith(".")
            ):
                continue
            init_file = item / "__init__.py"
            is_package = init_file.exists() or item.suffix in [
                ".dist-info",
                ".egg-info",
            ]
            if is_package:
                result = scan_package(item, site_dir)
                if result["error"] is None and result["has_entry_points"]:
                    pkg_name = result["name"]
                    if pkg_name not in processed:
                        processed.add(pkg_name)
                        packages_with_ep.append(
                            {
                                "name": pkg_name,
                                "entry_points": result["entry_points_data"],
                            }
                        )
    except:
        pass
    return packages_with_ep


if __name__ == "__main__":
    raise SystemExit(main())
