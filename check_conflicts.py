#!/data/data/com.termux/files/home/.local/bin/python
"""
check_conflicts.py

Detect (and optionally fix) files in the current directory that would
shadow a Python standard-library module or an installed PyPI package.

- stdlib names come from `dh.STDLIB` (a frozenset)
- PyPI names come from /sdcard/data/pip.json, a list of
  [package_name, download_count] records

Usage:
    python check_conflicts.py                       # report only
    python check_conflicts.py -a                    # rename to fix
    python check_conflicts.py -a -o report.json     # custom report path
    python check_conflicts.py -i                    # only installed PyPI pkgs

Exit codes:
    0 = no conflicts
    1 = conflicts found (fixed or not)
    2 = error
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from dh import STDLIB

PIP_JSON = Path("/sdcard/data/pip.json")
DEFAULT_REPORT = Path("conflict_report.json")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def normalize(name: str) -> str:
    """PEP 503 name normalisation: lowercase, '-'/'_'/'.' collapse to '-'."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def load_pypi_names(path: Path) -> set[str]:
    if not path.exists():
        print(f"warning: {path} not found -- PyPI check skipped", file=sys.stderr)
        return set()
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    names: set[str] = set()
    for rec in data:
        if isinstance(rec, (list, tuple)) and rec:
            names.add(normalize(str(rec[0])))
        elif isinstance(rec, str):
            names.add(normalize(rec))
    return names


def installed_distributions() -> set[str]:
    """Normalized names of distributions installed in the current interpreter."""
    try:
        from importlib.metadata import distributions  # py3.8+
    except ImportError:  # pragma: no cover - very old Python
        from importlib_metadata import distributions  # type: ignore

    names: set[str] = set()
    for dist in distributions():
        try:
            raw = dist.metadata["Name"]
        except Exception:
            raw = None
        if raw:
            names.add(normalize(str(raw)))
    return names


def collect_targets(root: Path):
    """Yield (path, import_name, kind) for things that can shadow imports."""
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix == ".py":
            yield p, p.stem, "module"
        elif p.is_dir() and (p / "__init__.py").is_file():
            yield p, p.name, "package"


def unique_target(path: Path) -> Path:
    """Return a non-existing sibling path with '_N' inserted before the suffix."""
    stem, suffix = path.stem, path.suffix
    n = 1
    while True:
        candidate = path.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Detect and optionally fix filename conflicts "
        "with stdlib / PyPI packages.",
    )
    ap.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="rename conflicting files by inserting '_N' before the extension",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"path of the JSON report (default: {DEFAULT_REPORT})",
    )
    ap.add_argument(
        "-d",
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="directory to scan (default: current directory)",
    )
    ap.add_argument(
        "-i",
        "--installed-only",
        action="store_true",
        help="only report PyPI conflicts for packages installed in this "
        "interpreter (stdlib check is unaffected)",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root: Path = args.dir.resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    # --- stdlib lookup ---------------------------------------------------
    stdlib_lookup: dict[str, str] = {}
    for n in STDLIB:
        stdlib_lookup.setdefault(normalize(n), n)

    # --- pypi lookup -----------------------------------------------------
    pypi = load_pypi_names(PIP_JSON)
    if args.installed_only:
        installed = installed_distributions()
        pypi &= installed

    conflicts: list[dict] = []
    checked = 0

    for path, import_name, kind in collect_targets(root):
        checked += 1
        key = normalize(import_name)

        real = stdlib_lookup.get(key)
        if real is not None:
            conflicts.append(
                {
                    "type": "stdlib",
                    "path": str(path),
                    "filename": path.name,
                    "import_name": import_name,
                    "shadows": real,
                    "kind": kind,
                }
            )
            continue  # stdlib takes priority; don't double-report

        if key in pypi:
            conflicts.append(
                {
                    "type": "pypi",
                    "path": str(path),
                    "filename": path.name,
                    "import_name": import_name,
                    "shadows": import_name,
                    "kind": kind,
                }
            )

    # --- autofix ---------------------------------------------------------
    renamed = 0
    if args.autofix:
        for c in conflicts:
            old = Path(c["path"])
            if not old.exists():
                c["fixed"] = False
                c["fix_error"] = "source disappeared"
                continue
            new = unique_target(old)
            try:
                old.rename(new)
                c["fixed"] = True
                c["new_path"] = str(new)
                c["new_filename"] = new.name
                renamed += 1
            except OSError as e:
                c["fixed"] = False
                c["fix_error"] = str(e)
    else:
        for c in conflicts:
            c["fixed"] = False

    # --- report ----------------------------------------------------------
    report = {
        "scanned_dir": str(root),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "autofix": args.autofix,
        "installed_only": args.installed_only,
        "checked": checked,
        "total_conflicts": len(conflicts),
        "renamed": renamed,
        "conflicts": conflicts,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # --- human summary to stdout ----------------------------------------
    print(f"Scanned {checked} importable item(s) in {root}")
    if args.installed_only:
        print("PyPI filter: installed-only")
    print(f"Report written to {args.output}")
    if not conflicts:
        print("OK: no filename conflicts detected.")
        return 0

    print(f"\nFound {len(conflicts)} conflict(s):")
    for c in conflicts:
        tag = f"[{c['type']}]"
        line = f"  {tag:<8} {c['filename']:<35} shadows {c['kind']} '{c['shadows']}'"
        if args.autofix and c.get("fixed"):
            line += f"  ->  {c['new_filename']}"
        elif args.autofix and not c.get("fixed"):
            line += f"  (fix failed: {c.get('fix_error', '?')})"
        print(line)

    if args.autofix:
        print(f"\nRenamed {renamed}/{len(conflicts)} item(s).")
    else:
        print("\nRun with -a / --autofix to rename them.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
