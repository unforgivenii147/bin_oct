#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a concise prompt to recreate this script: Copy installed Python packages (and their
dependencies from site-packages) into separate folders under ~/tmp/pkgs/<pkgname> using
multiprocessing.Pool.apply_async with 8 workers, loguru logging, pathlib paths, full type hints,
and docstrings. Usage: python script.py requests jinja2
"""

import argparse
import shutil
import site
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger

# Module-level constants
DEFAULT_OUTPUT_DIR: Path = Path("~/tmp/pkgs").expanduser()
NUM_WORKERS: int = 8


def get_site_packages_paths() -> list[Path]:
    """Return a list of existing site-packages directories."""
    paths: list[Path] = []
    for path_str in site.getsitepackages():
        paths.append(Path(path_str))
    user_site: str = site.getusersitepackages()
    if user_site:
        user_path: Path = Path(user_site)
        if user_path.exists():
            paths.append(user_path)
    return paths


def get_package_path(package_name: str, site_paths: list[Path]) -> Path | None:
    """Locate the directory of an installed package within site-packages."""
    for site_path in site_paths:
        pkg_path: Path = site_path / package_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        alt_name: str = package_name.replace("-", "_")
        pkg_path = site_path / alt_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        for item in site_path.iterdir():
            if item.is_dir() and item.name.lower().replace(
                "-", "_"
            ) == package_name.lower().replace("-", "_"):
                return item
    return None


def copy_package(
    args_tuple: tuple[str, Path, list[Path]],
) -> tuple[str, bool, str]:
    """Copy a single package's directory (excluding .pyc files) to the output directory."""
    package_name, output_dir, site_paths = args_tuple
    try:
        pkg_path: Path | None = get_package_path(package_name, site_paths)
        if not pkg_path:
            return package_name, False, "Package directory not found"

        dest_path: Path = output_dir / package_name
        if dest_path.exists():
            shutil.rmtree(dest_path)
        dest_path.mkdir(parents=True)

        for path in pkg_path.rglob("*"):
            if path.suffix == ".pyc":
                continue
            rel_path: Path = path.relative_to(pkg_path)
            dest_file: Path = dest_path / rel_path
            if path.is_dir():
                dest_file.mkdir(parents=True, exist_ok=True)
            else:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest_file)

        return package_name, True, f"Copied to {dest_path}"
    except Exception as e:
        return package_name, False, f"Error: {e!s}"


def main() -> int:
    """Parse arguments, copy requested packages, and report results."""
    parser = argparse.ArgumentParser(
        description="Copy installed Python packages into separate folders under ~/tmp/pkgs/<pkgname>"
    )
    parser.add_argument(
        "packages",
        nargs="+",
        help="Names of packages to copy",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output base directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args: argparse.Namespace = parser.parse_args()

    output_dir: Path = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    site_paths: list[Path] = get_site_packages_paths()
    print(f"Site-packages paths: {[str(p) for p in site_paths]}")

    process_args: list[tuple[str, Path, list[Path]]] = [
        (pkg, output_dir, site_paths) for pkg in args.packages
    ]

    successful: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    with Pool(processes=NUM_WORKERS) as pool:
        async_results: list[Any] = [
            pool.apply_async(copy_package, (arg,)) for arg in process_args
        ]
        total: int = len(async_results)
        for idx, async_result in enumerate(async_results, 1):
            pkg_name, success, message = async_result.get()
            if success:
                successful.append((pkg_name, message))
                print(f"[{idx}/{total}] ✓ {pkg_name}: {message}")
            else:
                failed.append((pkg_name, message))
                logger.error(f"[{idx}/{total}] ✗ {pkg_name}: {message}")

    print("\n" + "=" * 40)
    print("SUMMARY")
    print("=" * 40)
    print(f"Total packages processed: {len(process_args)}")
    print(f"✓ Successfully copied: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")

    if failed:
        logger.error("\nFailed packages:")
        for pkg, msg in failed:
            logger.error(f"  ✗ {pkg}: {msg}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
