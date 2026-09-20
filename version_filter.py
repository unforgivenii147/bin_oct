#!/data/data/com.termux/files/home/.local/bin/python
"""Remove obsolete or unwanted wheel files from a directory.

Rules:
  1. Drop ``py3-none-any`` wheels for packages in ``PY3_NONE_ANY_BLOCKLIST``.
  2. For date-stamped versions (``X.Y.Z-YYYYMMDD``), keep only the newest
     date per package; delete the rest.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WHL_DIRECTORY = Path(".")

# Matches: <name>-<version>[-<YYYYMMDD>]-<python tag>.whl
WHL_PATTERN = re.compile(
    r"(?P<name>[\w\-]+)"
    r"-(?P<version>[\d\.]+(?:-\d{8})?)"
    r"-(?P<python>"
    r"py3-none-any"
    r"|cp37-abi3-linux_armv8l"
    r"|cp312-cp312-linux_armv8l"
    r"|cp312-cp312-linux_arm"
    r"|py3-none-linux_armv8l"
    r")\.whl"
)

# Packages whose pure-python wheel (py3-none-any) should always be removed.
PY3_NONE_ANY_BLOCKLIST: frozenset[str] = frozenset({"pycryptodome", "matplotlib"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_wheel(filename: str) -> tuple[str, str, str] | None:
    """Return (package_name, version, python_variant) or None if unmatched."""
    match = WHL_PATTERN.match(filename)
    if match is None:
        return None
    return match.group("name"), match.group("version"), match.group("python")


def _latest_dates(parsed: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """Map package name -> newest date stamp for date-stamped versions."""
    latest: dict[str, str] = {}
    for _, name, version, _ in parsed:
        if "-" not in version:
            continue
        date_part = version.rsplit("-", 1)[-1]
        if date_part > latest.get(name, ""):
            latest[name] = date_part
    return latest


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def cleanup_wheels(whl_files: list[str], directory: Path = WHL_DIRECTORY) -> int:
    """Delete obsolete/unwanted wheels from *directory*.

    Returns the number of files removed.
    """
    # Parse each file once and keep only the ones that match our pattern.
    parsed: list[tuple[str, str, str, str]] = []
    for filename in whl_files:
        info = _parse_wheel(filename)
        if info is not None:
            parsed.append((filename, *info))

    latest_versions = _latest_dates(parsed)

    deleted = 0
    for filename, name, version, python_variant in parsed:
        # Rule 1: blocklisted pure-python wheels
        blocked_py3 = (
            name in PY3_NONE_ANY_BLOCKLIST and python_variant == "py3-none-any"
        )

        # Rule 2: outdated date-stamped versions
        outdated = "-" in version and version.rsplit("-", 1)[-1] != latest_versions.get(
            name
        )

        if not (blocked_py3 or outdated):
            continue

        (directory / filename).unlink()
        print(f"Deleted: {filename}")
        deleted += 1

    return deleted


def main() -> None:
    whl_files = [f for f in os.listdir(WHL_DIRECTORY) if f.endswith(".whl")]
    deleted = cleanup_wheels(whl_files)
    print(f"Number of files deleted: {deleted}")


if __name__ == "__main__":
    main()
