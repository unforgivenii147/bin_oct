#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that reinstalls all installed Python packages that expose
entry points (console_scripts, gui_scripts, or any custom entry-point group) using
pip's internal API with multiprocessing.Pool.apply_async concurrency (fixed at 8
workers), loguru-based logging, pathlib for all path operations, argparse CLI
(exclude/only/dry-run/include-deps/verbose/yes), interactive per-package
confirmation with an "all" option, and complete type annotations and docstrings.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import site
import sys
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Optional

from loguru import logger
from pip._internal.commands.install import InstallCommand
from pip._internal.exceptions import InstallationError
from pip._internal.utils.temp_dir import global_tempdir_manager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXED_WORKERS: int = 8
DEFAULT_EXCLUDES: set[str] = {"pip", "setuptools", "wheel"}
REINSTALL_FLAGS: tuple[str, ...] = ("--force-reinstall", "--no-cache-dir")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PackageInfo:
    """Metadata about an installed package that exposes entry points."""

    name: str
    version: str
    summary: str
    size: str
    groups: set[str] = field(default_factory=set)


@dataclass
class ReinstallResult:
    """Result of a reinstall attempt for a single package."""

    name: str
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def configure_logging(verbose: bool = False) -> None:
    """Configure loguru sinks for file and stderr output.

    Args:
        verbose: When True, emit DEBUG-level messages; otherwise INFO.
    """
    logger.remove()
    level: str = "DEBUG" if verbose else "INFO"
    log_path = Path(
        f"reinstall_entrypoint_packages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    logger.add(
        sink=str(log_path),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
    )
    logger.add(
        sink=sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> - "
        "<level>{level}</level> - {message}",
        colorize=True,
    )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def get_site_packages_dirs() -> list[Path]:
    """Return existing, unique site-packages directories (user + system)."""
    site_dirs: list[Path] = []
    user_site: str = site.getusersitepackages()
    if user_site:
        site_dirs.append(Path(user_site))
    for s in site.getsitepackages():
        site_dirs.append(Path(s))

    seen: set[str] = set()
    unique_dirs: list[Path] = []
    for d in site_dirs:
        if d.exists() and str(d) not in seen:
            seen.add(str(d))
            unique_dirs.append(d)
    return unique_dirs


def _entry_point_groups(dist: importlib.metadata.Distribution) -> set[str]:
    """Return the set of entry-point group names declared by ``dist``."""
    groups: set[str] = set()
    try:
        entry_points = dist.entry_points
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"Error reading entry points for {dist.name}: {exc}")
        return groups

    if not entry_points:
        return groups

    # importlib.metadata >= 3.10 exposes EntryPoints.select/groups
    if hasattr(entry_points, "select"):
        for group in ("console_scripts", "gui_scripts"):
            try:
                if list(entry_points.select(group=group)):
                    groups.add(group)
            except Exception:
                continue
        try:
            all_groups: set[str] = set(entry_points.groups)
        except Exception:
            all_groups = {
                getattr(ep, "group", "")
                for ep in entry_points
                if getattr(ep, "group", "")
            }
        for group in all_groups:
            groups.add(group)
    else:
        for ep in entry_points:
            g = getattr(ep, "group", None)
            if g:
                groups.add(g)
    return {g for g in groups if g}


def get_package_size(dist: importlib.metadata.Distribution) -> str:
    """Return a human-readable size estimate for the installed distribution."""
    try:
        dist_path_attr = getattr(dist, "_path", None)
        if dist_path_attr is None:
            return "Unknown"
        dist_path = Path(dist_path_attr)
        if dist_path.exists() and dist_path.is_dir():
            total_size: int = 0
            for item in dist_path.rglob("*"):
                if item.is_file():
                    try:
                        total_size += item.stat().st_size
                    except OSError:
                        continue
            if total_size > 1024 * 1024:
                return f"{total_size / (1024 * 1024):.1f} MB"
            if total_size > 1024:
                return f"{total_size / 1024:.1f} KB"
            return f"{total_size} B"
        return "Unknown"
    except Exception:
        return "Unknown"


def get_packages_with_entry_points() -> dict[str, PackageInfo]:
    """Return metadata for every installed distribution that exposes entry points."""
    packages: dict[str, PackageInfo] = {}
    try:
        distributions = list(importlib.metadata.distributions())
    except Exception as exc:
        logger.error(f"Error enumerating distributions: {exc}")
        return {}

    for dist in distributions:
        try:
            groups = _entry_point_groups(dist)
        except Exception as exc:
            logger.debug(f"Error checking entry points for {dist.name}: {exc}")
            continue
        if not groups:
            continue
        try:
            metadata = dist.metadata
        except Exception:
            metadata = None
        summary: str = (
            metadata.get("Summary", "No summary") if metadata else "No summary"
        ) or "No summary"
        packages[dist.name] = PackageInfo(
            name=dist.name,
            version=dist.version or "Unknown",
            summary=summary,
            size=get_package_size(dist),
            groups=groups,
        )
        logger.debug(f"Found entry points in {dist.name}: {groups}")
    return packages


# ---------------------------------------------------------------------------
# User interaction
# ---------------------------------------------------------------------------


def get_user_confirmation(
    package_name: str, package_data: PackageInfo, include_deps: bool = False
) -> str:
    """Prompt the user to confirm reinstallation of a package.

    Args:
        package_name: Name of the package being considered.
        package_data: Metadata for the package.
        include_deps: Whether dependencies will also be reinstalled.

    Returns:
        One of ``"yes"``, ``"no"``, or ``"all"``.
    """
    print("\n" + "=" * 40)
    print(f"📦 Package: {package_name}")
    print(f"   Version: {package_data.version}")
    print(f"   Entry points: {', '.join(sorted(package_data.groups))}")
    if package_data.summary and package_data.summary != "No summary":
        print(f"   Summary: {package_data.summary}")
    if package_data.size:
        print(f"   Size: {package_data.size}")
    if include_deps:
        print("   ⚠️  Will reinstall dependencies (may cause conflicts)")
    print("-" * 40)

    while True:
        response = (
            input("Reinstall this package? (y/n/a/?) [y/n/a/?]: ").lower().strip()
        )
        if response in ("y", "yes"):
            return "yes"
        if response in ("n", "no"):
            return "no"
        if response in ("a", "all"):
            return "all"
        if response in ("?", "help"):
            print("\nOptions:")
            print("  y/yes  - Yes, reinstall this package")
            print("  n/no   - No, skip this package")
            print("  a/all  - Yes to all remaining packages")
            print("  ?/help - Show this help message")
            continue
        print("Invalid response. Please enter 'y', 'n', 'a', or '?'")


# ---------------------------------------------------------------------------
# Reinstall worker (executed in child processes)
# ---------------------------------------------------------------------------


def reinstall_package_with_pip(
    package_name: str, include_deps: bool = False
) -> ReinstallResult:
    """Reinstall a single package using pip's internal ``InstallCommand`` API.

    Args:
        package_name: Distribution name to reinstall.
        include_deps: When True, allow dependency reinstallation.

    Returns:
        A :class:`ReinstallResult` describing the outcome.
    """
    try:
        install_cmd = InstallCommand()
        args: list[str] = ["install", *REINSTALL_FLAGS]
        if not include_deps:
            args.append("--no-deps")
        args.append(package_name)
        options, _ = install_cmd.parse_args(args)
        with global_tempdir_manager():
            try:
                install_cmd.run(options, args)
                print(f"✓ Successfully reinstalled: {package_name}")
                return ReinstallResult(
                    name=package_name,
                    success=True,
                    message="Successfully reinstalled",
                )
            except InstallationError as exc:
                msg = str(exc)
                logger.error(f"✗ Failed to reinstall {package_name}: {msg}")
                return ReinstallResult(package_name, False, msg)
    except Exception as exc:
        msg = str(exc)
        logger.error(f"✗ Error reinstalling {package_name}: {msg}")
        return ReinstallResult(package_name, False, msg)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _run_pool(packages: set[str], include_deps: bool) -> list[ReinstallResult]:
    """Run reinstallations via ``multiprocessing.Pool.apply_async`` with 8 workers."""
    results: list[ReinstallResult] = []
    with Pool(processes=FIXED_WORKERS) as pool:
        async_results: dict[AsyncResult[ReinstallResult], str] = {}
        for pkg in sorted(packages):
            ar: AsyncResult[ReinstallResult] = pool.apply_async(
                reinstall_package_with_pip, (pkg, include_deps)
            )
            async_results[ar] = pkg
        for ar, pkg in async_results.items():
            try:
                results.append(ar.get())
            except Exception as exc:
                logger.error(f"Unexpected error for {pkg}: {exc}")
                results.append(ReinstallResult(pkg, False, str(exc)))
    return results


def reinstall_entrypoint_packages(
    exclude_packages: set[str] | None = None,
    only_packages: set[str] | None = None,
    include_deps: bool = False,
    dry_run: bool = False,
    skip_confirmation: bool = False,
) -> None:
    """Reinstall every installed package that exposes entry points.

    Args:
        exclude_packages: Package names to skip. Defaults to pip/setuptools/wheel.
        only_packages: When provided, restrict reinstallation to these names.
        include_deps: When True, do not pass ``--no-deps`` to pip.
        dry_run: When True, only list packages without reinstalling.
        skip_confirmation: When True, skip interactive confirmation.
    """
    if exclude_packages is None:
        exclude_packages = set(DEFAULT_EXCLUDES)

    entry_point_packages: dict[str, PackageInfo] = get_packages_with_entry_points()
    if not entry_point_packages:
        logger.warning("No packages with entry points found!")
        return

    packages_to_reinstall: set[str] = (
        set(entry_point_packages.keys()) - exclude_packages
    )
    if only_packages:
        packages_to_reinstall &= only_packages

    print(f"Found {len(entry_point_packages)} packages with entry points")
    print(f"Will reinstall {len(packages_to_reinstall)} packages after filtering")

    if packages_to_reinstall:
        print("\nPackages with entry points:")
        for i, pkg in enumerate(sorted(packages_to_reinstall), 1):
            info = entry_point_packages[pkg]
            print(
                f"  {i:3d}. {pkg} (v{info.version}) - "
                f"entry points: {', '.join(sorted(info.groups))}"
            )

    if dry_run:
        print("\nDRY RUN - No packages will be reinstalled")
        return

    if not packages_to_reinstall:
        logger.warning("No packages to reinstall after filtering!")
        return

    if not skip_confirmation:
        selected: set[str] = set()
        all_selected: bool = False
        for pkg in sorted(packages_to_reinstall):
            if all_selected:
                selected.add(pkg)
                continue
            info = entry_point_packages[pkg]
            answer = get_user_confirmation(pkg, info, include_deps)
            if answer == "all":
                all_selected = True
                selected.add(pkg)
            elif answer == "yes":
                selected.add(pkg)
        packages_to_reinstall = selected
        if not packages_to_reinstall:
            logger.warning("No packages selected for reinstallation!")
            return
    else:
        print("Skipping confirmation - will reinstall all packages")

    print(
        f"\nStarting reinstallation of {len(packages_to_reinstall)} selected packages..."
    )

    results: list[ReinstallResult] = _run_pool(packages_to_reinstall, include_deps)

    successful: list[str] = [r.name for r in results if r.success]
    failed: list[tuple[str, str]] = [
        (r.name, r.message) for r in results if not r.success
    ]

    print("\n" + "=" * 40)
    print("REINSTALLATION SUMMARY")
    print("=" * 40)
    print(f"✓ Successfully reinstalled: {len(successful)} packages")
    print(f"✗ Failed to reinstall: {len(failed)} packages")

    if successful:
        print("\nSuccessfully reinstalled packages:")
        for name in sorted(successful):
            print(f"  ✓ {name}")

    if failed:
        print("\nFailed packages:")
        for name, error in failed:
            print(f"  ✗ {name}: {error[:100]}...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="Reinstall all Python packages with entry points using pip API",
        epilog="Compatible with Python 3.12+ and modern pip",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=sorted(DEFAULT_EXCLUDES),
        help="Packages to exclude from reinstallation",
    )
    parser.add_argument(
        "-o", "--only", nargs="+", help="Only reinstall specified packages"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be reinstalled without actually doing it",
    )
    parser.add_argument(
        "--include-deps",
        action="store_true",
        help="Also reinstall dependencies (not recommended, may cause conflicts)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation and reinstall all packages (use with caution)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI.

    Args:
        argv: Optional argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(verbose=bool(args.verbose))

    print(f"Starting package reinstallation with {FIXED_WORKERS} workers")
    print(
        "Reinstalling ONLY packages with entry points "
        "(console_scripts, gui_scripts, etc.)"
    )
    if args.yes:
        logger.warning(
            "⚠️  Auto-confirmation enabled. Will reinstall all packages without prompting!"
        )

    reinstall_entrypoint_packages(
        exclude_packages=set(args.exclude),
        only_packages=set(args.only) if args.only else None,
        include_deps=bool(args.include_deps),
        dry_run=bool(args.dry_run),
        skip_confirmation=bool(args.yes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
