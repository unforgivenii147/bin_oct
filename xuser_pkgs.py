#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import fnmatch
import importlib.metadata
import shutil
import site
from pathlib import Path


def get_user_site_path() -> Path:
    if not site.USER_SITE:
        site.main()
    return Path(site.USER_SITE).resolve()


def get_packages_with_entry_points() -> list[str]:
    packages_with_eps = []
    for dist in importlib.metadata.distributions():
        if dist.entry_points:
            packages_with_eps.append(dist.metadata["Name"])
    return sorted(packages_with_eps)


def get_matching_packages(pattern: str) -> list[str]:
    matching = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            matching.append(name)
    return matching


def resolve_package_list(
    patterns: list[str], entry_points_only: bool = False
) -> tuple[list[str], list[str]]:
    if entry_points_only:
        packages_with_eps = get_packages_with_entry_points()
        if not patterns:
            return packages_with_eps, []
        matched_packages = []
        unmatched_patterns = []
        for pattern in patterns:
            if any(c in pattern for c in "*?[]"):
                matches = [
                    pkg
                    for pkg in packages_with_eps
                    if fnmatch.fnmatch(pkg.lower(), pattern.lower())
                ]
                if matches:
                    matched_packages.extend(matches)
                else:
                    unmatched_patterns.append(pattern)
            else:
                if pattern in packages_with_eps:
                    matched_packages.append(pattern)
                else:
                    unmatched_patterns.append(pattern)
        return matched_packages, unmatched_patterns
    else:
        packages_with_eps = get_packages_with_entry_points()
        matched_packages = []
        unmatched_patterns = []
        for pattern in patterns:
            if any(c in pattern for c in "*?[]"):
                all_matches = get_matching_packages(pattern)
                matches = [pkg for pkg in all_matches if pkg in packages_with_eps]
                if matches:
                    matched_packages.extend(matches)
                else:
                    unmatched_patterns.append(pattern)
            else:
                if pattern in packages_with_eps:
                    matched_packages.append(pattern)
                else:
                    unmatched_patterns.append(pattern)
        return matched_packages, unmatched_patterns


def copy_single_file(
    record_row: list[str], dist_location: Path, target_dir: Path
) -> bool:
    if not record_row:
        return False
    relative_path_str = record_row[0]
    source_file = (dist_location / relative_path_str).resolve()
    if not source_file.is_file():
        return False
    if not source_file.is_relative_to(dist_location):
        return False
    destination_file = target_dir / relative_path_str
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_file, destination_file)
        return True
    except Exception as e:
        print(f"   ❌ Error copying {relative_path_str}: {e}")
        return False


def process_package(pkg_name: str, user_site: Path, base_target_dir: Path) -> str:
    try:
        dist = importlib.metadata.distribution(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return f"❌ Package '{pkg_name}' is not installed in this environment."
    dist_location = Path(dist.locate_file("")).resolve()
    if not dist_location.is_relative_to(user_site):
        return f"ℹ️  Package '{pkg_name}' found, but it is not installed in the user site folder (Location: {dist_location}). Skipping."
    try:
        files = dist.files
        if files is None:
            return f"❌ Package '{pkg_name}' has no file information available."
        record_file = None
        for file in files:
            if file.name == "RECORD":
                record_file = file.locate()
                break
        if not record_file:
            return f"❌ Package '{pkg_name}' RECORD file not found."
        record_path = Path(record_file)
        if not record_path.is_file():
            return f"❌ Package '{pkg_name}' RECORD file exists but is not accessible."
    except Exception as e:
        return f"❌ Failed to locate RECORD file for '{pkg_name}': {e}"
    pkg_target_dir = base_target_dir / pkg_name
    pkg_target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with record_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            records = list(reader)
    except Exception as e:
        return f"❌ Failed to parse RECORD file for '{pkg_name}': {e}"
    copied_count = 0
    with concurrent.futures.ThreadPoolExecutor() as file_executor:
        futures = [
            file_executor.submit(copy_single_file, row, dist_location, pkg_target_dir)
            for row in records
        ]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                copied_count += 1
    eps = dist.entry_points
    ep_info = ""
    if eps:
        ep_list = []
        for ep in eps:
            ep_list.append(f"{ep.group}:{ep.name}")
        ep_info = f" | Entry points: {', '.join(ep_list)}"
    return f"✅ Package '{pkg_name}' completely extracted! Copied {copied_count} files to {pkg_target_dir}{ep_info}"


def main():
    parser = argparse.ArgumentParser(
        description="Extract installed user-site Python packages that have entry points to ~/tmp/pkgs/<pkgname>",
        epilog="Examples:\n"
        "  python script.py requests              # Extract 'requests' if it has entry points\n"
        '  python script.py "req*"                 # Extract packages starting with "req" that have entry points\n'
        "  python script.py -e                     # Extract ALL packages with entry points\n"
        '  python script.py -e "django*"           # Extract django packages with entry points\n'
        "  python script.py -e --list-only         # List all packages with entry points",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "patterns",
        nargs="*",
        help='Package names or wildcard patterns (e.g., "a*" for all packages starting with "a")',
    )
    parser.add_argument(
        "-e",
        "--entry-points",
        action="store_true",
        help="Extract only packages that have entry points (console scripts, plugins, etc.)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list matching packages without extracting",
    )
    parser.add_argument(
        "--show-entry-points",
        action="store_true",
        help="Show detailed entry point information when listing",
    )
    args = parser.parse_args()
    if not args.entry_points and not args.patterns:
        parser.error(
            "Either provide package patterns or use -e flag for entry point packages"
        )
    matched_packages, unmatched_patterns = resolve_package_list(
        args.patterns if args.patterns else [], args.entry_points
    )
    seen = set()
    matched_packages = [x for x in matched_packages if not (x in seen or seen.add(x))]
    if unmatched_patterns:
        print(f"⚠️  No packages found matching: {', '.join(unmatched_patterns)}")
    if not matched_packages:
        if args.entry_points:
            print("❌ No packages with entry points found.")
        else:
            print("❌ No matching packages with entry points found.")
        return
    user_site = get_user_site_path()
    base_target_dir = Path.home() / "tmp" / "pkgs"
    print(f"🔍 System User-Site Path: {user_site}")
    print(f"📁 Destination Folder:   {base_target_dir}")
    if args.entry_points:
        print(f"📦 Found {len(matched_packages)} package(s) with entry points:")
    else:
        print(
            f"📦 Found {len(matched_packages)} matching package(s) with entry points:"
        )
    for pkg in matched_packages:
        if args.show_entry_points or args.list_only:
            try:
                dist = importlib.metadata.distribution(pkg)
                eps = dist.entry_points
                if eps:
                    print(f"   - {pkg}")
                    for ep in sorted(eps, key=lambda x: (x.group, x.name)):
                        print(f"     [{ep.group}] {ep.name} = {ep.value}")
                else:
                    print(f"   - {pkg} (no entry points)")
            except Exception:
                print(f"   - {pkg}")
        else:
            print(f"   - {pkg}")
    print("-" * 40)
    if args.list_only:
        return
    packages_to_extract = []
    for pkg in matched_packages:
        try:
            dist = importlib.metadata.distribution(pkg)
            if dist.entry_points:
                packages_to_extract.append(pkg)
            else:
                print(f"ℹ️  Package '{pkg}' has no entry points. Skipping.")
        except Exception:
            print(f"⚠️  Could not verify entry points for '{pkg}'. Skipping.")
    if not packages_to_extract:
        print("❌ No packages with entry points to extract.")
        return
    print(f"🔄 Extracting {len(packages_to_extract)} packages with entry points...")
    with concurrent.futures.ThreadPoolExecutor() as pkg_executor:
        future_to_pkg = {
            pkg_executor.submit(process_package, pkg, user_site, base_target_dir): pkg
            for pkg in packages_to_extract
        }
        for future in concurrent.futures.as_completed(future_to_pkg):
            pkg_name = future_to_pkg[future]
            try:
                result_message = future.result()
                print(result_message)
            except Exception as exc:
                print(
                    f"❌ Package '{pkg_name}' generated an unhandled exception: {exc}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
