#!/data/data/com.termux/files/home/.local/bin/python
"""Find files listed by `dpkg -L` that are missing on disk: enumerate installed packages with `dpkg -l`, verify each package's files in a multiprocessing pool of 8 workers via `Pool.starmap`, skip `share/man|info|doc|LICENSES` paths, and write `missing_files.json` and `missing.txt` using loguru for progress."""

import json
import subprocess
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final

from loguru import logger

MAX_WORKERS: Final[int] = 8
DPKG_TIMEOUT_SECONDS: Final[int] = 5
IGNORED_SHARE_SUBDIRS: Final[frozenset[str]] = frozenset(
    {"man", "info", "doc", "LICENSES"}
)
DEFAULT_OUTPUT_NAME: Final[str] = "missing_files.json"
MISSING_TXT_NAME: Final[str] = "missing.txt"


def should_ignore(file_path: str) -> bool:
    """Return ``True`` for paths under `share/man`, `share/info`, `share/doc`, or `share/LICENSES`."""
    parts: tuple[str, ...] = Path(file_path).parts
    for i in range(len(parts) - 1):
        if parts[i] == "share" and parts[i + 1] in IGNORED_SHARE_SUBDIRS:
            return True
    return False


def check_package_files(pkg_name: str) -> tuple[str, list[str] | None]:
    """Return ``(package, missing_files_or_None)`` for a single dpkg package.

    ``None`` means either the package has no missing files or its listing
    could not be obtained.
    """
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["dpkg", "-L", pkg_name],
            capture_output=True,
            text=True,
            timeout=DPKG_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            return pkg_name, None

        missing: list[str] = []
        for file_path in result.stdout.strip().split("\n"):
            if not file_path or should_ignore(file_path):
                continue
            p: Path = Path(file_path)
            if p.is_dir():
                continue
            if not p.exists():
                missing.append(file_path)

        return pkg_name, missing if missing else None
    except subprocess.TimeoutExpired:
        return pkg_name, None
    except Exception as e:
        logger.warning("Error checking {}: {}", pkg_name, e)
        return pkg_name, None


def _list_installed_packages() -> list[str]:
    """Return the names of all currently installed dpkg packages."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["dpkg", "-l"], capture_output=True, text=True, check=False
    )
    packages: list[str] = []
    for line in result.stdout.split("\n"):
        if line.startswith("ii"):
            fields: list[str] = line.split()
            if len(fields) >= 2:
                packages.append(fields[1])
    return packages


def main() -> None:
    """CLI entry point: scan all installed packages and write missing-file reports."""
    output_file: Path = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_OUTPUT_NAME)
    )
    missing_txt: Path = Path(MISSING_TXT_NAME)

    packages: list[str] = _list_installed_packages()
    if not packages:
        logger.warning("No installed packages found (is dpkg available?)")
        return

    logger.info("Scanning {} packages with {} workers...", len(packages), MAX_WORKERS)

    jobs: list[tuple[str]] = [(pkg,) for pkg in packages]

    results: dict[str, list[str]] = {}
    with Pool(processes=MAX_WORKERS) as pool:
        for i, (pkg, missing) in enumerate(
            pool.starmap(check_package_files, jobs), start=1
        ):
            if missing:
                results[pkg] = missing
            if i % 10 == 0:
                logger.info("  {}/{}", i, len(packages))

    try:
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        with missing_txt.open("w", encoding="utf-8") as f:
            f.write("\n".join(results.keys()))
    except OSError as e:
        logger.error("Error writing output: {}", e)
        sys.exit(1)

    total_missing: int = sum(len(files) for files in results.values())
    logger.info("✓ {} packages with missing files → {}", len(results), output_file)
    logger.info("  Total missing: {}", total_missing)


if __name__ == "__main__":
    raise SystemExit(main())
