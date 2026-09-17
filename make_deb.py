#!/data/data/com.termux/files/home/.local/bin/python
"""
Download .deb files for installed apt packages into ~/debs, skipping LLVM/Clang/Rust
toolchain packages. Uses python-apt to enumerate and fetch packages, a fixed
multiprocessing.Pool of 8 workers for parallelism, and loguru for logging. Accepts
optional package names as CLI args; otherwise processes every installed package.
"""

import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import apt  # type: ignore[import-untyped]
import apt.package  # type: ignore[import-untyped]
from loguru import logger

DEB_DIR: Final[Path] = Path.home() / "debs"
LOG_FILE: Final[Path] = Path.home() / "make_deb.log"
MAX_WORKERS: Final[int] = 8

EXCLUDED_PKGS: Final[frozenset[str]] = frozenset(
    {
        "llvm",
        "clang",
        "libllvm",
        "libclang",
        "rust",
        "cargo",
        "lld",
        "lldb",
        "compiler-rt",
        "libc++",
        "libc++abi",
        "rust-stdlib",
        "rust-analyzer",
        "cargo-c",
    }
)

# Configure loguru sinks (console + log file).
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add(
    LOG_FILE, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}"
)


def should_exclude(pkg_name: str) -> bool:
    """
    Decide whether a package name should be skipped.

    Args:
        pkg_name: The Debian package name.

    Returns:
        ``True`` if the package matches the exclusion list or contains any of
        the LLVM/Clang/Rust/Cargo substrings.
    """
    pkg_lower: str = pkg_name.lower()
    if pkg_lower in EXCLUDED_PKGS:
        return True
    if any(exclude in pkg_lower for exclude in ("llvm", "clang")):
        return True
    return any(exclude in pkg_lower for exclude in ("rust", "cargo"))


def get_installed_packages() -> list[str]:
    """
    Enumerate installed apt packages using :mod:`apt`, excluding toolchain packages.

    Returns:
        A sorted list of package names that are installed and not excluded.
    """
    try:
        cache: apt.Cache = apt.Cache()
        packages: list[str] = [
            pkg.name
            for pkg in cache
            if pkg.is_installed and not should_exclude(pkg.name)
        ]
        return sorted(packages)
    except Exception as exc:
        logger.error(f"Failed to get installed packages: {exc}")
        return []


def create_deb_for_package(pkg_name: str) -> bool:
    """
    Download the .deb file for a single package into :data:`DEB_DIR`.

    Uses ``apt.package.Version.fetch_binary`` from python-apt instead of shelling
    out to ``apt download``. If a matching ``.deb`` already exists, it is reused.

    Args:
        pkg_name: The Debian package name to fetch.

    Returns:
        ``True`` if the .deb is present (already existing or freshly downloaded),
        otherwise ``False``.
    """
    try:
        DEB_DIR.mkdir(parents=True, exist_ok=True)
        deb_file: Path = DEB_DIR / f"{pkg_name}.deb"
        if deb_file.exists():
            print(f"✓ {pkg_name}.deb already exists, skipping...")
            return True

        cache: apt.Cache = apt.Cache()
        if pkg_name not in cache:
            logger.error(f"✗ Package {pkg_name} not found in apt cache")
            return False

        pkg: apt.package.Package = cache[pkg_name]
        candidate: apt.package.Version | None = pkg.candidate
        if candidate is None:
            logger.error(f"✗ No candidate version available for {pkg_name}")
            return False

        print(f"⟳ Creating .deb for {pkg_name}...")
        result_path: str | None = candidate.fetch_binary(dest_dir=str(DEB_DIR))

        if result_path and Path(result_path).exists():
            print(f"✓ Successfully created {pkg_name}.deb")
            return True
        if deb_file.exists():
            print(f"✓ Successfully created {pkg_name}.deb")
            return True

        logger.warning(f"⚠ Fetch returned no file for {pkg_name}")
        return False
    except Exception as exc:
        logger.error(f"✗ Error creating {pkg_name}.deb: {exc}")
        return False


def process_packages(packages: list[str]) -> tuple[int, int]:
    """
    Download .deb files for the given packages using a fixed pool of workers.

    Args:
        packages: Candidate package names. Excluded names are filtered out.

    Returns:
        A tuple ``(successful, failed)`` count of download outcomes.
    """
    successful: int = 0
    failed: int = 0

    filtered: list[str] = [p for p in packages if not should_exclude(p)]
    if not filtered:
        logger.warning("No packages to process (all excluded or empty list)")
        return 0, 0

    print(f"Processing {len(filtered)} packages with {MAX_WORKERS} workers...")

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[bool]] = [
            pool.apply_async(create_deb_for_package, (pkg,)) for pkg in filtered
        ]
        for pkg, async_res in zip(filtered, async_results):
            try:
                if async_res.get():
                    successful += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(f"✗ Unexpected error for {pkg}: {exc}")
                failed += 1

    return successful, failed


def main() -> None:
    """Entry point: parse args, enumerate packages, and download .deb files."""
    if len(sys.argv) > 1:
        packages: list[str] = sys.argv[1:]
        print(f"Processing specified packages: {', '.join(packages)}")
    else:
        print("Getting list of all installed packages...")
        packages = get_installed_packages()
        print(f"Found {len(packages)} installed packages (after exclusions)")

    if not packages:
        logger.error("No packages to process")
        sys.exit(1)

    successful: int
    failed: int
    successful, failed = process_packages(packages)

    print("=" * 40)
    print(f"Summary: {successful} successful, {failed} failed")
    print(f"Total: {successful + failed}")
    print(f".deb files saved in: {DEB_DIR}")
    print(f"Log file: {LOG_FILE}")

    if failed > 0:
        logger.warning(f"Some packages failed. Check {LOG_FILE} for details.")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
