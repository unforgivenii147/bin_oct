#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import email.parser
import platform
import sys
import zipfile
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path


def get_wheel_tags() -> str:
    python_version = f"{sys.version_info.major}{sys.version_info.minor}"
    abi_tag = f"cp{python_version}"
    system = platform.system().lower()
    arch = platform.machine().lower()
    if system == "linux" and "android" in platform.platform().lower():
        platform_tag = "android"
    elif system == "linux":
        platform_tag = "linux_x86_64" if arch == "x86_64" else arch
    else:
        platform_tag = "any"
    return f"cp{python_version}-{abi_tag}-{platform_tag}"


def get_package_info(pkg_path):
    info = {
        "name": pkg_path.name,
        "version": "0.0.0",
        "files": [],
        "data_files": [],
        "scripts": [],
        "has_so": False,
    }
    for dist_dir in pkg_path.parent.glob(f"{pkg_path.name}*.dist-info"):
        metadata_path = dist_dir / "METADATA"
        if metadata_path.exists():
            content = metadata_path.read_text(encoding="utf-8", errors="ignore")
            parser = email.parser.Parser()
            msg = parser.parsestr(content)
            info["version"] = msg.get("Version", "0.0.0")
            info["name"] = msg.get("Name", pkg_path.name)
            break
    for egg_dir in pkg_path.parent.glob(f"{pkg_path.name}*.egg-info"):
        metadata_path = egg_dir / "PKG-INFO"
        if metadata_path.exists():
            content = metadata_path.read_text(encoding="utf-8", errors="ignore")
            parser = email.parser.Parser()
            msg = parser.parsestr(content)
            info["version"] = msg.get("Version", "0.0.0")
            info["name"] = msg.get("Name", pkg_path.name)
            break
    if pkg_path.is_dir() and any(pkg_path.rglob("*.so")):
        info["has_so"] = True
    return info


def collect_package_files(pkg_path, verbose=False):
    files = []
    site_packages = pkg_path.parent
    if pkg_path.is_dir():
        for path in pkg_path.rglob("*"):
            if path.is_file() and not path.suffix == ".pyc":
                rel_path = path.relative_to(site_packages)
                files.append((rel_path, path))
    elif pkg_path.is_file() and pkg_path.suffix == ".py":
        rel_path = pkg_path.relative_to(site_packages)
        files.append((rel_path, pkg_path))
    data_dirs = ["share", "etc", "lib"]
    for data_dir in data_dirs:
        data_path = site_packages.parent / data_dir / pkg_path.name
        if data_path.exists():
            for path in data_path.rglob("*"):
                if path.is_file():
                    rel_path = path.relative_to(site_packages.parent)
                    files.append((rel_path, path))
    bin_path = site_packages.parent / "bin"
    if bin_path.exists():
        for script_path in bin_path.glob("*"):
            if script_path.is_file() and (
                script_path.name.startswith(pkg_path.name)
                or script_path.name == pkg_path.name
            ):
                rel_path = script_path.relative_to(site_packages.parent)
                files.append((rel_path, script_path))
    if verbose:
        print(f"  Collected {len(files)} files for {pkg_path.name}")
    return files


def create_wheel(
    pkg_path, wheels_dir, dryrun: bool = False, verbose: bool = False
) -> bool:
    try:
        pkg_info = get_package_info(pkg_path)
        pkg_name = pkg_info["name"]
        pkg_version = pkg_info["version"]
        wheel_tag = get_wheel_tags() if pkg_info["has_so"] else "py3-none-any"
        wheel_name = f"{pkg_name}-{pkg_version}-{wheel_tag}.whl"
        wheel_path = wheels_dir / wheel_name
        if wheel_path.exists():
            if verbose:
                print(f"  Wheel already exists: {wheel_name} (skipping)")
            return True
        if dryrun:
            print(f"[DRYRUN] Would repack {pkg_name}-{pkg_version} -> {wheel_path}")
            return True
        if verbose:
            print(f"Creating {wheel_name}...")
        files = collect_package_files(pkg_path, verbose)
        if not files:
            print(f"Warning: No files found for {pkg_name}")
            return False
        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as wheel:
            dist_info_dir = f"{pkg_name}-{pkg_version}.dist-info"
            metadata = f"""Metadata-Version: 2.1
Name: {pkg_name}
Version: {pkg_version}
Generator: custom-repacker
"""
            wheel.writestr(f"{dist_info_dir}/METADATA", metadata)
            wheel_metadata = f"""Wheel-Version: 1.0
Generator: custom-repacker
Root-Is-Purelib: {str(not pkg_info["has_so"]).lower()}
Tag: {wheel_tag}
"""
            wheel.writestr(f"{dist_info_dir}/WHEEL", wheel_metadata)
            if pkg_path.is_dir():
                top_level = [pkg_path.name]
                wheel.writestr(f"{dist_info_dir}/top_level.txt", "\n".join(top_level))
            record_entries = []
            for rel_path, abs_path in files:
                archive_path = str(rel_path)
                wheel.write(abs_path, archive_path)
                file_size = abs_path.stat().st_size
                record_entries.append(f"{archive_path},sha256=,{file_size}")
                if verbose:
                    print(f"  Added: {archive_path}")
            record_path = f"{dist_info_dir}/RECORD"
            record_content = "\n".join(record_entries) + f"\n{record_path},,\n"
            wheel.writestr(record_path, record_content)
        if verbose:
            print(
                f"✓ Created {wheel_name} ({len(files)} files, {wheel_path.stat().st_size} bytes)"
            )
        return True
    except Exception as e:
        print(f"Error repacking {pkg_path.name}: {e}")
        if verbose:
            import traceback

            traceback.print_exc()
        return False


def get_packages(site_packages_dir: Path, package_names=None):
    packages = []
    ignore_dirs = {
        "__pycache__",
        "pip",
        "setuptools",
        "wheel",
        "_distutils_hack",
        "pkg_resources",
    }
    for item in site_packages_dir.iterdir():
        if item.name in ignore_dirs:
            continue
        if item.name.startswith("_"):
            continue
        if item.is_dir():
            if (item / "__init__.py").exists() or any(
                item.parent.glob(f"{item.name}*.dist-info")
            ):
                packages.append(item)
        elif item.suffix == ".py" and item.name != "__init__.py":
            packages.append(item)
    if package_names:
        filtered = []
        for pkg in packages:
            pkg_name = pkg.stem if pkg.suffix == ".py" else pkg.name
            if pkg_name in package_names:
                filtered.append(pkg)
        packages = filtered
    return packages


def repack_sequential(packages, wheels_dir: Path, dryrun, verbose):
    results = []
    for pkg in packages:
        results.append(create_wheel(pkg, wheels_dir, dryrun, verbose))
    return results


def repack_parallel(packages, wheels_dir: Path, dryrun, verbose) -> list[bool]:
    repack_func = partial(
        create_wheel, wheels_dir=wheels_dir, dryrun=dryrun, verbose=verbose
    )
    with Pool(processes=cpu_count()) as pool:
        results = pool.map(repack_func, packages)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repack site-packages packages as wheel files"
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Repack all packages (uses multiprocessing)",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Show what would be done without actual repacking",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "packages", nargs="*", help="Package names to repack (sequential mode)"
    )
    args = parser.parse_args()
    wheels_dir = Path.home() / "tmp" / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    if not args.dryrun:
        print(f"Wheels will be stored in: {wheels_dir}")
    possible_paths = [
        Path(sys.executable).parent
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        Path(__file__).parent if "__file__" in dir() else Path.cwd(),
    ]
    site_packages = None
    for path in possible_paths:
        if path.exists() and path.is_dir():
            site_packages = path
            break
    if not site_packages:
        print("Could not find site-packages directory")
        return
    print(f"Using site-packages: {site_packages}")
    if args.packages:
        packages = get_packages(site_packages, args.packages)
    elif args.all or not args.packages:
        packages = get_packages(site_packages)
    else:
        packages = []
    if not packages:
        print("No packages found to repack")
        return
    print(f"Found {len(packages)} package(s) to repack")
    if args.dryrun:
        print("\n[DRYRUN MODE] No files will be created")
    use_parallel = args.all and len(packages) > 1
    if use_parallel:
        print(f"Using parallel mode with {cpu_count()} processes")
        results = repack_parallel(packages, wheels_dir, args.dryrun, args.verbose)
    else:
        if len(packages) > 1:
            print("Using sequential mode (use -a for parallel)")
        results = repack_sequential(packages, wheels_dir, args.dryrun, args.verbose)
    success_count = sum(results)
    print(f"\nComplete: {success_count}/{len(packages)} packages repacked successfully")
    if success_count > 0 and not args.dryrun:
        print(f"\nWheels saved in: {wheels_dir}")
        wheel_files = list(wheels_dir.glob("*.whl"))
        if wheel_files:
            print("\nCreated wheels:")
            for wheel in sorted(
                wheel_files, key=lambda x: x.stat().st_mtime, reverse=True
            )[:10]:
                size_mb = wheel.stat().st_size / (1024 * 1024)
                print(f"  {wheel.name} ({size_mb:.2f} MB)")
            if len(wheel_files) > 10:
                print(f"  ... and {len(wheel_files) - 10} more")


if __name__ == "__main__":
    raise SystemExit(main())
