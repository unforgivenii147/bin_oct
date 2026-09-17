#!/data/data/com.termux/files/home/.local/bin/python
"""
List installed packages (in the user site-packages directory) that ship
entry points, and write their names to a file.

Entry points are declared via ``entry_points.txt`` inside the package's
``*.dist-info`` or ``*.egg-info`` metadata directory. Packages with entry
points are the ones that install console scripts (e.g. ``pip``, ``flake8``).

Output file: ``/sdcard/data/pkgs_with_scripts`` — one package name per line.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OUTPUT_FILE = Path("/sdcard/data/pkgs_with_scripts")
ENTRY_POINTS_FILE = "entry_points.txt"

# Metadata directory suffixes to skip when enumerating package folders.
METADATA_SUFFIXES: tuple[str, ...] = (".dist-info", ".egg-info")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def _has_entry_points(site_dir: Path, package_name: str, suffix: str) -> bool:
    """
    Return True if a metadata directory matching ``package_name`` (with the
    given suffix) exists under ``site_dir`` and contains an entry-points file.

    The glob pattern is ``"<name>-*<suffix>"``, matching pip / setuptools
    naming (``<name>-<version>.dist-info``). The hyphen prevents a shorter
    package name from accidentally matching a longer one — e.g. ``foo``
    matching ``foobar-1.0.dist-info``.
    """
    for meta in site_dir.glob(f"{package_name}-*{suffix}"):
        if (meta / ENTRY_POINTS_FILE).exists():
            return True
    return False


def find_packages_with_entry_points(site_dir: Path) -> list[str]:
    """
    Return the sorted names of packages in ``site_dir`` that declare entry
    points via either a ``.dist-info`` or ``.egg-info`` metadata directory.
    """
    found: list[str] = []

    for entry in site_dir.iterdir():
        # Only real directories can be packages.
        if not entry.is_dir():
            continue

        # Skip metadata directories themselves.
        if entry.name.endswith(METADATA_SUFFIXES):
            continue

        # Prefer .dist-info (modern pip) but fall back to .egg-info (legacy).
        has_ep = _has_entry_points(
            site_dir, entry.name, ".dist-info"
        ) or _has_entry_points(site_dir, entry.name, ".egg-info")

        if has_ep:
            found.append(entry.name)

    return sorted(found)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    """Entry point: discover packages with entry points, print and save them."""
    user_site = Path(site.getusersitepackages())

    # The user site dir may not exist on a fresh interpreter.
    if not user_site.is_dir():
        print(f"user site-packages not found: {user_site}", file=sys.stderr)
        return 1

    names = find_packages_with_entry_points(user_site)

    # Print to stdout for interactive use.
    for name in names:
        print(name)

    # Make sure the destination directory exists (it's on /sdcard, which
    # may not have a "data" folder yet on a fresh Termux install).
    try:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text("\n".join(names), encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write {OUTPUT_FILE}: {exc}", file=sys.stderr)
        return 1

    print(f"\nWrote {len(names)} package name(s) to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code cleanly.
    raise SystemExit(main())
