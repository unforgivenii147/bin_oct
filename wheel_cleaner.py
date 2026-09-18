#!/data/data/com.termux/files/home/.local/bin/python
# -*- coding: utf-8 -*-
"""
wheel_cleaner.py
================

Unified tool for finding "empty" Python wheels (wheels that ship only
metadata / ``*.dist-info`` and no importable code) and for finding broken
installations whose ``.dist-info`` directory contains only itself.

Standard library only -- no third-party dependencies.

Subcommands
-----------

``wheels``
    Scan a directory for ``*.whl`` files, classify them and optionally move
    the empty ones into a destination subdirectory.

``installed``
    Scan a site-packages directory for ``*.dist-info`` directories whose
    ``RECORD`` file only references files inside that same directory
    (i.e. the package was installed from an empty wheel).

``scan``
    Do both of the above in one pass.

Examples
--------

    # Just report empty wheels in the current directory
    python wheel_cleaner.py wheels

    # Report + move them (no prompt)
    python wheel_cleaner.py wheels . --move -y

    # Same as ewhl2.py: audit installed packages and prompt before moving
    python wheel_cleaner.py wheels . --move --check-installed

    # Recursively find wheels that contain no code at all
    python wheel_cleaner.py wheels . -r --detect no-code

    # Inspect a site-packages directory
    python wheel_cleaner.py installed --path /usr/lib/python3/dist-packages

    # Combined report (same as emptypkg.py)
    python wheel_cleaner.py scan .

Mapping from the original scripts
---------------------------------

    ewhl.py               ->  python wheel_cleaner.py wheels . --move -y
    ewhl2.py              ->  python wheel_cleaner.py wheels . --move --check-installed
    emptypkg.py           ->  python wheel_cleaner.py scan .
    emptywhl.py           ->  python wheel_cleaner.py wheels --detect record --move -y
    find_empty_wheels.py  ->  python wheel_cleaner.py wheels . -r --detect no-code --move -y

Detectors (``--detect``, repeatable / comma-separated)
------------------------------------------------------

    dist-info-only  every archive entry lives under a single ``*.dist-info/``
                    directory (default; the documented intent of ewhl.py)
    record          every ``RECORD`` row points inside the ``*.dist-info/``
                    directory (emptywhl.py)
    no-code         the archive contains no ``.py`` / ``.so`` / ``.pyi`` file
                    (find_empty_wheels.py)
    no-payload      literal ewhl.py / ewhl2.py logic: no ``.py`` file *and*
                    no other non-metadata file.  Kept for exact backwards
                    compatibility -- it is arguably buggy because it only
                    ignores a *top-level* ``dist-info/`` directory.
    all             union of all of the above

A wheel is reported as empty when **any** selected detector matches.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import zipfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["main"]

# ---------------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------------

DEFAULT_DEST = "empty_wheels"
DEFAULT_DETECTOR = "dist-info-only"

#: File extensions that make a wheel "non-empty" for the ``no-code`` detector.
_CODE_SUFFIXES: Tuple[str, ...] = (".py", ".so", ".pyi")


# ---------------------------------------------------------------------------
# Detectors -- each returns True when the wheel looks "empty"
# ---------------------------------------------------------------------------


def _dist_info_prefix(names: Sequence[str]) -> Optional[str]:
    """Return the ``<name>.dist-info/`` prefix of the wheel, or ``None``.

    Prefers a real directory entry (``foo-1.0.dist-info/``) over an entry
    that merely *contains* ``.dist-info`` somewhere in its path.
    """
    for name in names:
        if name.endswith(".dist-info/"):
            return name  # already ends with "/"
    for name in names:
        if ".dist-info/" in name:
            return name.split("/")[0] + "/"
    return None


def _detect_dist_info_only(zf: zipfile.ZipFile, names: Sequence[str]) -> bool:
    """True when every entry lives under a single ``*.dist-info/`` directory."""
    prefix = _dist_info_prefix(names)
    if prefix is None:
        return False
    return all(name.endswith("/") or name.startswith(prefix) for name in names)


def _detect_record(zf: zipfile.ZipFile, names: Sequence[str]) -> bool:
    """True when every ``RECORD`` row points inside the ``*.dist-info/`` dir."""
    prefix = _dist_info_prefix(names)
    if prefix is None:
        return False
    record = f"{prefix}RECORD"
    if record not in names:
        return False
    try:
        with zf.open(record) as handle:
            reader = csv.reader(line.decode("utf-8") for line in handle)
            for row in reader:
                if not row:
                    continue
                if not row[0].startswith(prefix):
                    return False
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile, OSError):
        return False
    return True


def _detect_no_code(zf: zipfile.ZipFile, names: Sequence[str]) -> bool:
    """True when the archive contains no ``.py`` / ``.so`` / ``.pyi`` file."""
    return not any(name.lower().endswith(_CODE_SUFFIXES) for name in names)


def _detect_no_payload(zf: zipfile.ZipFile, names: Sequence[str]) -> bool:
    """Literal port of ``ewhl.py``'s check (kept for exact compatibility).

    .. warning::
       The original only ignores a *top-level* ``dist-info/`` directory, so
       for a normal wheel such as ``foo-1.0.dist-info/METADATA`` the entry is
       considered "payload" and the wheel is never reported as empty.  Use
       ``--detect dist-info-only`` (the default) for the intended behaviour.
    """
    has_py = any(name.endswith(".py") for name in names)
    has_other = any(
        not name.startswith(("dist-info/", "__pycache__/"))
        and not name.endswith("/")
        and not name.endswith(".dist-info/")
        for name in names
    )
    return not (has_py or has_other)


DetectorFn = Callable[[zipfile.ZipFile, Sequence[str]], bool]

DETECTORS: Dict[str, DetectorFn] = {
    "dist-info-only": _detect_dist_info_only,
    "record": _detect_record,
    "no-code": _detect_no_code,
    "no-payload": _detect_no_payload,
}

DETECTOR_HELP = """\
detectors:
  dist-info-only  every entry lives under a single *.dist-info/ directory (default)
  record          every RECORD row points inside the *.dist-info/ directory
  no-code         the archive contains no .py / .so / .pyi file
  no-payload      literal ewhl.py logic (no .py file and no extra file)
  all             union of every detector above
"""


def resolve_detectors(raw: Optional[Iterable[str]]) -> List[str]:
    """Expand ``--detect`` values (repeatable, comma separated, ``all``)."""
    if not raw:
        return [DEFAULT_DETECTOR]

    chosen: List[str] = []
    for item in raw:
        for part in str(item).split(","):
            part = part.strip().lower()
            if not part:
                continue
            if part in ("all", "any"):
                for name in DETECTORS:
                    if name not in chosen:
                        chosen.append(name)
            elif part in DETECTORS:
                if part not in chosen:
                    chosen.append(part)
            else:
                raise SystemExit(
                    f"Error: unknown detector {part!r}. "
                    f"Choose from: {', '.join(DETECTORS)} (or 'all')"
                )
    return chosen or [DEFAULT_DETECTOR]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def wheel_is_empty(path: Path, detectors: Sequence[str], quiet: bool = False) -> bool:
    """Return True when *path* matches any of the selected detectors."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            return any(DETECTORS[det](zf, names) for det in detectors)
    except zipfile.BadZipFile:
        if not quiet:
            print(f"  Warning: {path} is not a valid zip file", file=sys.stderr)
        return False
    except OSError as exc:
        if not quiet:
            print(f"  Warning: cannot read {path}: {exc}", file=sys.stderr)
        return False


def find_wheels(
    directory: Path, recursive: bool, exclude: Optional[Path] = None
) -> List[Path]:
    """Collect ``*.whl`` files in *directory*, optionally recursively.

    Files located inside *exclude* (typically the destination folder) are
    skipped so repeated runs do not re-report already-moved wheels.
    """
    candidates = directory.rglob("*.whl") if recursive else directory.glob("*.whl")
    result: List[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if exclude is not None:
            try:
                candidate.relative_to(exclude)
                continue
            except ValueError:
                pass
        result.append(candidate)
    return sorted(result)


def unique_path(directory: Path, name: str) -> Path:
    """Return a collision-free path inside *directory* for *name*."""
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while target.exists():
        target = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


def parse_wheel_name(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort ``(distribution, version)`` extraction from a wheel name.

    Mirrors ``ewhl2.py``: take the first two dash-separated components of the
    filename stem and normalise ``_`` to ``-`` in the distribution name.
    """
    parts = path.stem.split("-")
    if len(parts) >= 2:
        return parts[0].replace("_", "-"), parts[1]
    return None, None


def default_site_packages() -> Path:
    """The interpreter's ``purelib`` directory (site-packages)."""
    return Path(sysconfig.get_paths()["purelib"])


# ---------------------------------------------------------------------------
# Installed-package inspection (pip based) -- from ewhl2.py
# ---------------------------------------------------------------------------


def installed_packages() -> Dict[str, str]:
    """Map of ``distribution-name.lower() -> version`` for the current env."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:  # noqa: BLE001 - pip may be missing entirely
        print(f"Warning: could not list installed packages: {exc}", file=sys.stderr)
        return {}

    packages: Dict[str, str] = {}
    for line in proc.stdout.strip().splitlines():
        if "==" in line:
            name, version = line.split("==", 1)
            packages[name.lower()] = version
    return packages


def pip_show(name: str) -> Optional[Dict[str, str]]:
    """Return the parsed output of ``pip show <name>`` (or ``None``)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show", name],
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    info: Dict[str, str] = {}
    for line in proc.stdout.strip().splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            info[key.lower()] = value
    return info


def pip_show_location_and_files(name: str) -> Tuple[Optional[str], bool]:
    """Return ``(location, has_real_files)`` from ``pip show -f <name>``.

    ``has_real_files`` is True when the ``Files:`` section lists anything
    outside a ``.dist-info`` directory, i.e. the installation looks complete.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show", "-f", name],
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return None, False
    if proc.returncode != 0:
        return None, False

    lines = proc.stdout.strip().split("\n")
    location: Optional[str] = None
    has_files = False
    for index, line in enumerate(lines):
        if line.startswith("Location:"):
            location = line.split(":", 1)[1].strip()
        elif line.startswith("Files:"):
            window = lines[index + 1 : index + 10]
            if any(entry.strip() and ".dist-info" not in entry for entry in window):
                has_files = True
    return location, has_files


# ---------------------------------------------------------------------------
# Empty installed packages (site-packages) -- from emptypkg.py
# ---------------------------------------------------------------------------


def is_empty_dist_info(dist_info: Path) -> bool:
    """True when every ``RECORD`` entry resolves inside *dist_info* itself."""
    record = dist_info / "RECORD"
    if not record.is_file():
        return False

    root = dist_info.resolve()
    try:
        with record.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                try:
                    target = (dist_info.parent / row[0]).resolve()
                except OSError:
                    return False
                try:
                    target.relative_to(root)
                except ValueError:
                    return False
    except (OSError, UnicodeDecodeError, csv.Error):
        return False
    return True


def find_empty_installed_packages(site_packages: Path) -> List[str]:
    """List ``*.dist-info`` directories in *site_packages* that are empty."""
    found: List[str] = []
    if not site_packages.is_dir():
        return found
    for entry in sorted(site_packages.iterdir()):
        if (
            entry.name.endswith(".dist-info")
            and entry.is_dir()
            and is_empty_dist_info(entry)
        ):
            found.append(str(entry))
    return found


# ---------------------------------------------------------------------------
# Subcommand: wheels
# ---------------------------------------------------------------------------


def cmd_wheels(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: directory '{args.directory}' does not exist", file=sys.stderr)
        return 2

    detectors = resolve_detectors(args.detect)
    dest_dir = directory / args.dest
    wheels = find_wheels(directory, args.recursive, exclude=dest_dir)

    if not wheels:
        print(f"No .whl files found in {directory}")
        return 0

    print(
        f"Found {len(wheels)} wheel file(s) to check "
        f"(detectors: {', '.join(detectors)})"
    )

    installed: Dict[str, str] = {}
    if args.check_installed:
        installed = installed_packages()
        print(f"Found {len(installed)} installed package(s) in the current environment")

    empty: List[Path] = []
    valid: List[Path] = []
    conflicts: List[Tuple[Path, str, str]] = []

    for wheel in wheels:
        if wheel_is_empty(wheel, detectors, quiet=args.quiet):
            print(f"Checking {wheel.name} ... EMPTY")
            empty.append(wheel)
        else:
            print(f"Checking {wheel.name} ... OK")
            valid.append(wheel)
            continue

        if not args.check_installed:
            continue

        package, _ = parse_wheel_name(wheel)
        if not package:
            continue
        version = installed.get(package.lower())
        if version is None:
            if args.verbose:
                print(f"  info: package '{package}' is not installed")
            continue

        print(f"  WARNING: package '{package}' is INSTALLED (version {version})")
        location, has_files = pip_show_location_and_files(package)
        if location:
            print(f"  installed at: {location}")
            if not has_files:
                print("  installation appears incomplete!")
        conflicts.append((wheel, package, version))

    # -- summary ---------------------------------------------------------
    print("-" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total wheels : {len(wheels)}")
    print(f"Valid wheels : {len(valid)}")
    print(f"Empty wheels : {len(empty)}")

    if conflicts:
        print(
            f"\nCRITICAL: {len(conflicts)} empty wheel(s) correspond to INSTALLED packages!"
        )
        for wheel, package, version in conflicts:
            print(f"  - {wheel.name} -> {package}=={version}")
        print("\nRECOMMENDATIONS:")
        print("  1. DO NOT move/delete these wheels if you still need the packages")
        print("  2. The packages are likely broken installs")
        print("  3. Consider reinstalling them:")
        for _, package, _ in conflicts:
            print(f"     {sys.executable} -m pip uninstall {package} -y")
            print(f"     {sys.executable} -m pip install {package}")

    if not empty:
        print("\nNo empty wheels found!")
        return 0

    if args.dry_run or not args.move:
        print(
            f"\nFound {len(empty)} empty wheel(s) "
            f"(report only -- pass --move to relocate them)"
        )
        for wheel in empty:
            print(f"  {wheel.name}")
        return 0

    # -- decide what to move --------------------------------------------
    installed_paths = {wheel for wheel, _, _ in conflicts}
    moveable = [w for w in empty if w not in installed_paths]

    if not args.assume_yes:
        if conflicts:
            question = (
                f"\n{len(conflicts)} empty wheel(s) belong to INSTALLED packages. "
                f"Move only the remaining {len(moveable)} uninstalled empty wheel(s)? (y/n): "
            )
        else:
            question = f"\nMove {len(empty)} empty wheel(s) to '{args.dest}/'? (y/n): "
        answer = input(question).strip().lower()
        if answer not in ("y", "yes"):
            print("No wheels were moved.")
            return 0

    if not moveable:
        print("Nothing to move (every empty wheel belongs to an installed package).")
        return 0

    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for wheel in moveable:
        target = unique_path(dest_dir, wheel.name)
        shutil.move(str(wheel), str(target))
        print(f"Moved: {wheel.name} -> {args.dest}/{target.name}")
        moved += 1

    print(f"\nMoved {moved} empty wheel(s) to {dest_dir}")
    print(f"Valid wheels remaining: {len(valid)}")

    if conflicts:
        print("\n" + "=" * 40)
        print("IMPORTANT ACTIONS TO TAKE")
        print("-" * 40)
        print("These packages were installed from empty wheels and are likely broken:")
        for _, package, version in conflicts:
            print(f"  - {package} (version {version})")
        print("\nTo fix them:")
        for _, package, _ in conflicts:
            print(f"   {sys.executable} -m pip uninstall {package}")
            print(
                f"   {sys.executable} -m pip install {package}  # or use a valid wheel"
            )

    return 0


# ---------------------------------------------------------------------------
# Subcommand: installed
# ---------------------------------------------------------------------------


def cmd_installed(args: argparse.Namespace) -> int:
    site_packages = Path(args.path) if args.path else default_site_packages()
    if not site_packages.is_dir():
        print(
            f"Error: site-packages directory '{site_packages}' does not exist",
            file=sys.stderr,
        )
        return 2

    found = find_empty_installed_packages(site_packages)
    if not found:
        print(f"No empty installed packages found in {site_packages}.")
        return 0

    print(f"=== Empty installed packages ({site_packages}) ===")
    for path in found:
        print(f"  {path}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: scan  (emptypkg.py behaviour)
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: directory '{args.directory}' does not exist", file=sys.stderr)
        return 2

    site_packages = Path(args.path) if args.path else default_site_packages()
    detectors = resolve_detectors(args.detect)

    empty_packages = (
        find_empty_installed_packages(site_packages) if site_packages.is_dir() else []
    )
    empty_wheels = [
        wheel
        for wheel in find_wheels(directory, args.recursive)
        if wheel_is_empty(wheel, detectors, quiet=args.quiet)
    ]

    if empty_packages:
        print("\n=== Empty installed packages (site-packages) ===")
        for path in empty_packages:
            print(f"  {path}")
    else:
        print("\nNo empty installed packages found.")

    if empty_wheels:
        print("\n=== Empty wheel files ===")
        for wheel in empty_wheels:
            print(f"  {wheel}")
    else:
        print("\nNo empty wheel files found.")

    if not empty_packages and not empty_wheels:
        print("\nNo empty packages or wheels found.")

    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wheel_cleaner.py",
        description=(
            "Detect (and optionally move) 'empty' Python wheels -- wheels that "
            "contain only *.dist-info metadata and no importable code -- and "
            "find broken installations in site-packages."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""\
            {DETECTOR_HELP}
            original script mapping:
              ewhl.py               ->  wheels . --move -y
              ewhl2.py              ->  wheels . --move --check-installed
              emptypkg.py           ->  scan .
              emptywhl.py           ->  wheels --detect record --move -y
              find_empty_wheels.py  ->  wheels . -r --detect no-code --move -y
            """
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{wheels,installed,scan}",
    )

    # -- wheels ----------------------------------------------------------
    wheels = subparsers.add_parser(
        "wheels",
        help="scan a directory for empty .whl files",
        description="Scan a directory for empty .whl files and optionally move them.",
    )
    wheels.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="directory containing .whl files (default: current directory)",
    )
    wheels.add_argument(
        "-d",
        "--dest",
        default=DEFAULT_DEST,
        help=f"destination subdirectory name (default: {DEFAULT_DEST!r})",
    )
    wheels.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="search subdirectories recursively (find_empty_wheels.py behaviour)",
    )
    wheels.add_argument(
        "--detect",
        action="append",
        metavar="NAME",
        help="empty-wheel detector(s); repeatable or comma separated "
        f"({', '.join(DETECTORS)}, or 'all'). Default: {DEFAULT_DETECTOR}",
    )
    wheels.add_argument(
        "--move",
        action="store_true",
        help="move the empty wheels into --dest (default: report only)",
    )
    wheels.add_argument(
        "-y",
        "--yes",
        "--auto-move-all",
        dest="assume_yes",
        action="store_true",
        help="do not prompt before moving (ewhl2.py --auto-move-all / ewhl.py behaviour)",
    )
    wheels.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly report only, never move anything",
    )
    wheels.add_argument(
        "--check-installed",
        action="store_true",
        help="cross-check empty wheels against the packages installed in the "
        "current environment (ewhl2.py behaviour)",
    )
    wheels.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show detailed per-wheel output",
    )
    wheels.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress warnings about unreadable/invalid wheel files",
    )
    wheels.set_defaults(func=cmd_wheels)

    # -- installed -------------------------------------------------------
    installed = subparsers.add_parser(
        "installed",
        help="find empty *.dist-info directories in site-packages",
        description="Find installed packages that consist of metadata only.",
    )
    installed.add_argument(
        "--path",
        default=None,
        help="site-packages directory to inspect (default: sysconfig purelib)",
    )
    installed.set_defaults(func=cmd_installed)

    # -- scan ------------------------------------------------------------
    scan = subparsers.add_parser(
        "scan",
        help="report empty installed packages AND empty wheels (emptypkg.py)",
        description="Combined report: empty site-packages entries and empty wheels.",
    )
    scan.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="directory containing .whl files (default: current directory)",
    )
    scan.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="search subdirectories recursively",
    )
    scan.add_argument(
        "--path",
        default=None,
        help="site-packages directory to inspect (default: sysconfig purelib)",
    )
    scan.add_argument(
        "--detect",
        action="append",
        metavar="NAME",
        help="empty-wheel detector(s); repeatable or comma separated "
        f"({', '.join(DETECTORS)}, or 'all'). Default: {DEFAULT_DETECTOR}",
    )
    scan.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress warnings about unreadable/invalid wheel files",
    )
    scan.set_defaults(func=cmd_scan)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse *argv* and dispatch to the selected subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) is None:
        parser.print_help()
        return 2

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
