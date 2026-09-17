#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import multiprocessing as mp
import sys
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path


def find_site_packages() -> Path | None:
    for path in sys.path:
        p = Path(path)
        if p.name == "site-packages" and p.exists():
            return p
    return None


def find_bin_dir() -> Path | None:
    prefix = Path(sys.prefix)
    bin_dir = prefix / "bin"
    if bin_dir.exists():
        return bin_dir
    for possible_bin in [
        Path("/data/data/com.termux/files/usr/bin"),
        Path("/usr/bin"),
        Path("/usr/local/bin"),
    ]:
        if possible_bin.exists():
            return possible_bin
    return None


def parse_entry_points(entry_points_file: Path) -> list[tuple[str, str]]:
    scripts = []
    if not entry_points_file.exists():
        return scripts
    try:
        config = ConfigParser()
        config.read(entry_points_file)
        if config.has_section("console_scripts"):
            for script_name, module_entry in config.items("console_scripts"):
                scripts.append((script_name.strip(), module_entry.strip()))
    except Exception as e:
        print(f"Error parsing {entry_points_file}: {e}")
    return scripts


def check_package(args: tuple[Path, Path]) -> dict:
    dist_info_dir, bin_dir = args
    package_name = dist_info_dir.name.replace(".dist-info", "")
    entry_points_file = dist_info_dir / "entry_points.txt"
    result = {
        "package": package_name,
        "path": str(dist_info_dir),
        "missing_scripts": [],
        "defined_scripts": [],
        "has_entry_points": False,
    }
    scripts = parse_entry_points(entry_points_file)
    if not scripts:
        return result
    result["has_entry_points"] = True
    for script_name, module_entry in scripts:
        result["defined_scripts"].append(script_name)
        script_path = bin_dir / script_name
        if not script_path.exists():
            result["missing_scripts"].append(
                {
                    "name": script_name,
                    "entry": module_entry,
                    "expected_path": str(script_path),
                }
            )
    return result


def find_dist_info_dirs(site_packages: Path) -> list[Path]:
    return sorted(site_packages.glob("*.dist-info"))


def main():
    print("-" * 40)
    print("Python Package Script Checker for Termux")
    print("-" * 40)
    print()
    site_packages = find_site_packages()
    if not site_packages:
        print("ERROR: Could not find site-packages directory!")
        sys.exit(1)
    bin_dir = find_bin_dir()
    if not bin_dir:
        print("ERROR: Could not find bin directory!")
        sys.exit(1)
    print(f"Site-packages: {site_packages}")
    print(f"Bin directory: {bin_dir}")
    print(f"Python version: {sys.version}")
    print()
    dist_info_dirs = find_dist_info_dirs(site_packages)
    print(f"Found {len(dist_info_dirs)} installed packages")
    print()
    args = [(d, bin_dir) for d in dist_info_dirs]
    cpu_count = min(mp.cpu_count(), len(dist_info_dirs) if dist_info_dirs else 1)
    print(f"Using {cpu_count} processes for scanning...")
    with mp.Pool(processes=cpu_count) as pool:
        results = pool.map(check_package, args)
    packages_with_entry_points = [r for r in results if r["has_entry_points"]]
    packages_with_missing = [r for r in results if r["missing_scripts"]]
    total_missing = sum(len(r["missing_scripts"]) for r in packages_with_missing)
    print()
    print("-" * 40)
    print("SCAN RESULTS")
    print("-" * 40)
    print()
    print(f"Total packages scanned: {len(results)}")
    print(f"Packages with console_scripts: {len(packages_with_entry_points)}")
    print(f"Packages with missing scripts: {len(packages_with_missing)}")
    print(f"Total missing scripts: {total_missing}")
    print()
    report_lines = []
    report_lines.append("=" * 40)
    report_lines.append("PYTHON PACKAGE SCRIPT INTEGRITY REPORT")
    report_lines.append("=" * 40)
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Site-packages: {site_packages}")
    report_lines.append(f"Bin directory: {bin_dir}")
    report_lines.append(f"Python: {sys.version}")
    report_lines.append("")
    report_lines.append(f"Total packages scanned: {len(results)}")
    report_lines.append(
        f"Packages with console_scripts: {len(packages_with_entry_points)}"
    )
    report_lines.append(f"Packages with missing scripts: {len(packages_with_missing)}")
    report_lines.append(f"Total missing scripts: {total_missing}")
    report_lines.append("")
    if packages_with_missing:
        report_lines.append("-" * 40)
        report_lines.append("PACKAGES WITH MISSING SCRIPTS")
        report_lines.append("-" * 40)
        report_lines.append("")
        for pkg in packages_with_missing:
            report_lines.append(f"Package: {pkg['package']}")
            report_lines.append(f"Location: {pkg['path']}")
            report_lines.append(f"Missing scripts: {len(pkg['missing_scripts'])}")
            report_lines.append("")
            for script in pkg["missing_scripts"]:
                report_lines.append(f"  • {script['name']}")
                report_lines.append(f"    Entry point: {script['entry']}")
                report_lines.append(f"    Expected at: {script['expected_path']}")
                report_lines.append("")
    else:
        report_lines.append("✓ No missing scripts found!")
        report_lines.append("")
    report_lines.append("-" * 40)
    report_lines.append("SUMMARY")
    report_lines.append("-" * 40)
    report_lines.append("")
    for pkg in sorted(results, key=lambda x: x["package"]):
        if pkg["has_entry_points"]:
            status = (
                "✓ OK"
                if not pkg["missing_scripts"]
                else f"✗ Missing {len(pkg['missing_scripts'])}"
            )
            report_lines.append(f"{pkg['package']:40s} {status}")
    for line in report_lines:
        print(line)
    output_file = (
        Path.cwd()
        / f"missing_scripts_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    try:
        output_file.write_text("\n".join(report_lines) + "\n")
        print(f"\nReport saved to: {output_file}")
    except Exception as e:
        print(f"\nError saving report: {e}")
    if packages_with_missing:
        print(f"""
⚠️  Found {total_missing} missing script(s) in {len(packages_with_missing)} package(s).""")
        print("These packages may need to be reinstalled.")
        sys.exit(1)
    else:
        print("\n✓ All console scripts are properly installed.")
        sys.exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
