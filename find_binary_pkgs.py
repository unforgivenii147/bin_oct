#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a script that scans installed Python packages in site-packages, detects which
packages contain compiled binary extensions (non-pure Python), and writes the list of
binary packages to an output file.

The script uses multiprocessing.Pool.apply_async with a fixed pool of 8 workers to check
packages in parallel. It uses loguru for logging and pathlib for all path handling.

CLI:
    python script.py [-o OUTPUT] [-v]

Behavior:
    - Discovers site-packages paths via the `site` module.
    - Enumerates installed distributions via importlib.metadata.
    - For each distribution, locates its package directory under site-packages and checks
      for binary file extensions (.so, .pyd, .dll, .dylib).
    - Packages containing such files are reported as binary (non-pure Python).
    - Writes results to the output file as `package==version` lines.
    - Logs progress and a summary using loguru.
"""

from __future__ import annotations

import argparse
import site
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path

import importlib_metadata
from loguru import logger

# Module-level constants
NUM_WORKERS: int = 8
BINARY_EXTENSIONS: tuple[str, ...] = (".so", ".pyd", ".dll", ".dylib")


def get_site_packages_paths() -> list[Path]:
    """Return a list of existing site-packages directories (system and user)."""
    paths: list[Path] = []
    for path in site.getsitepackages():
        paths.append(Path(path))
    user_site = site.getusersitepackages()
    if user_site:
        user_path = Path(user_site)
        if user_path.exists():
            paths.append(user_path)
    return paths


def get_installed_packages() -> list[tuple[str, str]]:
    """Return a list of (name, version) tuples for all installed distributions."""
    packages: list[tuple[str, str]] = []
    all_dists = list(importlib_metadata.distributions())
    for dist in all_dists:
        try:
            name = dist.metadata.get("Name")
            version = dist.version
            if name and version:
                packages.append((name, version))
        except Exception as e:
            logger.warning(f"Error getting info for package: {e}")
    return packages


def find_package_path(package_name: str, site_paths: list[Path]) -> Path | None:
    """Locate the directory for a package within the given site-packages paths."""
    for site_path in site_paths:
        pkg_path = site_path / package_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        alt_name = package_name.replace("-", "_")
        pkg_path = site_path / alt_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        for item in site_path.iterdir():
            if item.is_dir() and item.name.lower().replace(
                "-", "_"
            ) == package_name.lower().replace("-", "_"):
                return item
    return None


def is_pure_python(package_name: str, site_paths: list[Path]) -> bool:
    """Return True if the package contains no compiled binary extensions."""
    pkg_path = find_package_path(package_name, site_paths)
    if not pkg_path:
        logger.warning(f"Cannot find package directory for {package_name}")
        return True

    for ext in BINARY_EXTENSIONS:
        try:
            if any(pkg_path.rglob(f"*{ext}")):
                return False
        except (PermissionError, OSError):
            continue
    return True


def check_package(args_tuple: tuple[str, str, list[Path]]) -> tuple[str, str, bool]:
    """Worker function: return (name, version, is_pure) for one package."""
    package_name, version, site_paths = args_tuple
    try:
        is_pure = is_pure_python(package_name, site_paths)
        return package_name, version, is_pure
    except Exception as e:
        logger.error(f"Error checking {package_name}: {e}")
        return package_name, version, True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Find non-pure Python packages in site-packages"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="binary_packages.txt",
        help="Output file for package list (default: binary_packages.txt)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    return parser.parse_args()


def write_output(output: str, binary_packages: Iterable[tuple[str, str]]) -> Path:
    """Write the binary packages list to the output file, return the resolved path."""
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("# Binary (non-pure Python) packages found in site-packages\n")
        f.write("# Format: package_name==version\n\n")
        f.writelines(f"{pkg}=={ver}\n" for pkg, ver in sorted(binary_packages))
    return output_path


def main() -> int:
    """Entry point: scan packages, detect binaries, write results, log summary."""
    args = parse_args()

    if args.verbose:
        logger.remove()
        logger.add(lambda msg: print(msg, end=""), level="DEBUG")

    site_paths = get_site_packages_paths()
    print(f"Site-packages paths: {[str(p) for p in site_paths]}")

    all_packages = get_installed_packages()
    print(f"Found {len(all_packages)} installed packages")

    if not all_packages:
        logger.error("No packages found")
        return 1

    process_args: list[tuple[str, str, list[Path]]] = [
        (pkg, ver, site_paths) for pkg, ver in all_packages
    ]

    binary_packages: list[tuple[str, str]] = []
    pure_packages: list[tuple[str, str]] = []
    total: int = len(process_args)
    completed: int = 0

    print(f"Checking packages using {NUM_WORKERS} parallel workers...")

    with Pool(processes=NUM_WORKERS) as pool:
        async_results = [
            (pool.apply_async(check_package, (arg,)), arg[0]) for arg in process_args
        ]
        for async_result, pkg_name in async_results:
            completed += 1
            result_name, version, is_pure = async_result.get()
            if not is_pure:
                binary_packages.append((result_name, version))
                print(f"[{completed}/{total}] ✓ {result_name} is BINARY")
            else:
                pure_packages.append((result_name, version))
                logger.debug(f"[{completed}/{total}] - {result_name} is pure Python")

    output_path = write_output(args.output, binary_packages)

    print("=" * 40)
    print("SUMMARY")
    print("=" * 40)
    print(f"Total packages checked: {total}")
    print(f"Binary packages found: {len(binary_packages)}")
    print(f"Pure Python packages: {len(pure_packages)}")
    print(f"Results saved to: {output_path}")

    if binary_packages:
        print("Binary packages:")
        for pkg, ver in binary_packages[:10]:
            print(f"  - {pkg}=={ver}")
        if len(binary_packages) > 10:
            print(f"  ... and {len(binary_packages) - 10} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
