#!/data/data/com.termux/files/home/.local/bin/python
"""
Report packages in the user's site-packages directory that have no
associated ``.dist-info`` / ``.egg-info`` metadata declaring entry points.

This is useful for spotting "orphan" directories left behind by manual
copies, uninstalls that skipped metadata, or vendored code that was never
installed via pip. A directory is considered "installed" if a sibling
``<name>-*.dist-info`` or ``<name>-*.egg-info`` directory exists AND
contains an ``entry_points.txt`` file.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

# Metadata directory suffixes we deliberately skip when enumerating
# package folders (they are metadata, not packages themselves).
_METADATA_SUFFIXES: tuple[str, ...] = (".dist-info", ".egg-info")

# File whose presence marks a metadata dir as "has entry points".
_ENTRY_POINTS_FILE = "entry_points.txt"


def has_entry_points_metadata(
    package_dir: Path,
    search_root: Path,
) -> bool:
    """
    Return True if a matching metadata directory with entry_points.txt exists.

    Args:
        package_dir: The candidate package directory (e.g. ``.../requests``).
        search_root: The site-packages directory to search inside.

    Matching rules:
        The metadata directory must start with ``<name>-`` (name followed by
        a hyphen), which is how pip/setuptools name ``*.dist-info`` and
        ``*.egg-info`` directories. This avoids false positives where a
        shorter name would otherwise match a longer package's metadata
        (e.g. ``foo`` incorrectly matching ``foobar-1.0.dist-info``).
    """
    name = package_dir.name

    for suffix in _METADATA_SUFFIXES:
        # e.g. "requests-*.dist-info" / "requests-*.egg-info"
        for meta in search_root.glob(f"{name}-*{suffix}"):
            if (meta / _ENTRY_POINTS_FILE).exists():
                return True

    return False


def find_orphan_packages(site_dir: Path) -> list[str]:
    """
    Return a sorted list of package directory names in ``site_dir`` that
    have no entry-points metadata.

    Non-directories and metadata directories themselves are ignored.
    """
    orphans: list[str] = []

    # ``iterdir`` is non-recursive by design: top-level packages only.
    for entry in site_dir.iterdir():
        # Only real directories matter; skip files, symlinks-to-files, etc.
        if not entry.is_dir():
            continue

        # Skip metadata directories themselves.
        if entry.name.endswith(_METADATA_SUFFIXES):
            continue

        if not has_entry_points_metadata(entry, site_dir):
            orphans.append(entry.name)

    return sorted(orphans)


def main() -> int:
    """Entry point: print every orphaned package directory name."""
    # ``getusersitepackages`` returns a string path to the user site dir.
    user_site = Path(site.getusersitepackages())

    # Guard: the user site directory may not exist yet on a fresh install.
    if not user_site.is_dir():
        print(f"user site-packages not found: {user_site}", file=sys.stderr)
        return 1

    for name in find_orphan_packages(user_site):
        print(name)

    return 0


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code cleanly.
    raise SystemExit(main())
