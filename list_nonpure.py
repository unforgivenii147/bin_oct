#!/data/data/com.termux/files/home/.local/bin/python
"""
List user-installed packages in site-packages that contain compiled
extension modules (``.so`` / ``.pyd`` / ``.dylib`` / ``.dll``).

Uses ``pathlib`` exclusively — no ``os`` / ``os.walk``.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Suffixes we treat as "compiled extension" files.
COMPILED_SUFFIXES: frozenset[str] = frozenset({".so", ".pyd", ".dylib", ".dll"})

# Metadata directory suffixes to skip when enumerating packages.
METADATA_SUFFIXES: tuple[str, ...] = (".dist-info", ".egg-info")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def has_compiled_extension(package_dir: Path) -> bool:
    """
    Return True if ``package_dir`` contains any compiled extension file
    at any depth.

    Uses ``Path.rglob("*")`` for the recursive walk and checks each file's
    suffix (lower-cased, so ``.SO`` on case-insensitive filesystems still
    matches) against ``COMPILED_SUFFIXES``.
    """
    for entry in package_dir.rglob("*"):
        # ``rglob`` yields directories too; only files matter here.
        if entry.is_file() and entry.suffix.lower() in COMPILED_SUFFIXES:
            return True
    return False


def find_packages_with_compiled_extensions(site_dir: Path) -> list[str]:
    """
    Return a sorted list of package names in ``site_dir`` that contain at
    least one compiled extension file.

    Only top-level directories are considered packages. Metadata
    directories (``*.dist-info`` / ``*.egg-info``) are skipped.
    """
    matches: list[str] = []

    for entry in site_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.endswith(METADATA_SUFFIXES):
            continue
        if has_compiled_extension(entry):
            matches.append(entry.name)

    return sorted(matches)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    """Entry point: print every user package that ships a compiled module."""
    user_site = Path(site.getusersitepackages())

    # Fresh interpreters may not have created the user site dir yet.
    if not user_site.is_dir():
        print(f"user site-packages not found: {user_site}", file=sys.stderr)
        return 1

    for name in find_packages_with_compiled_extensions(user_site):
        print(name)

    return 0


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code cleanly.
    raise SystemExit(main())
