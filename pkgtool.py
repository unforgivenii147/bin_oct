#!/data/data/com.termux/files/home/.local/bin/python
"""
pkgtool.py — Unified package-management toolkit.

Merges 11 originals into a single argparse CLI:

    aptin.py                    -> pkgtool.py apt-install <pattern> [--no-confirm]
    system_pkg_reinstaller.py   -> pkgtool.py apt-reinstall <file>
    install_wheels.py           -> pkgtool.py wheel-install [--dir .] [--workers 8]
    piu.py                      -> pkgtool.py wheel-install-local <wheel...>
    move_installed_wheels.py    -> pkgtool.py wheel-move-installed
    piprm.py                    -> pkgtool.py pip-uninstall <pattern> -b subprocess
    pu.py                       -> pkgtool.py pip-uninstall <pattern> -b api --no-confirm
    rm_flake8_plugins.py        -> pkgtool.py pip-uninstall-flake8 [--dry-run]
    pure_pypkg_reinstaller.py   -> pkgtool.py pip-reinstall-list <file>
    pure_teinstaller.py         -> pkgtool.py pip-reinstall-pypi <file>
    reinstaller.py              -> pkgtool.py pip-reinstall-entry-points

Third-party packages (optional, all have graceful fallbacks):

    rapidfuzz    — fuzzy pip-package matching (falls back to difflib)
    packaging    — wheel filename / version parsing (wheel-move-installed)
    pip          — required only by `-b api` pip backend

Examples
--------
    pkgtool.py apt-install "python*" --no-confirm
    pkgtool.py apt-reinstall ~/missing.txt
    pkgtool.py wheel-install --dir ./wheels --workers 4
    pkgtool.py wheel-install-local ./dist/foo-1.0-py3-none-any.whl
    pkgtool.py wheel-move-installed --src /sdcard/whl --dst /sdcard/installed
    pkgtool.py pip-uninstall numpy -b api --no-confirm
    pkgtool.py pip-uninstall-flake8 --dry-run
    pkgtool.py pip-reinstall-list ~/missing.txt --dry-run
    pkgtool.py pip-reinstall-pypi pure.txt --workers 8
    pkgtool.py pip-reinstall-entry-points --yes --dry-run
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence


# ============================================================================
# Optional third-party dependencies
# ============================================================================
try:
    from rapidfuzz import fuzz as _rapidfuzz  # type: ignore
except ImportError:  # pragma: no cover
    _rapidfuzz = None

try:
    import importlib.metadata as _im  # type: ignore
except ImportError:  # pragma: no cover
    import importlib_metadata as _im  # type: ignore  # noqa: F401

try:
    from packaging.utils import parse_wheel_filename  # type: ignore
    from packaging.version import Version  # type: ignore
except ImportError:  # pragma: no cover
    parse_wheel_filename = None  # type: ignore
    Version = None  # type: ignore


# ============================================================================
# Shared helpers  (formerly the `dh` module)
# ============================================================================
_ANSI = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "grey": "\033[90m",
    "reset": "\033[0m",
}
_COLOR_ON = sys.stdout.isatty()


def cprint(msg: str, color: str = "white", end: str = "\n") -> None:
    """Colour-aware print."""
    if _COLOR_ON and color in _ANSI:
        print(f"{_ANSI[color]}{msg}{_ANSI['reset']}", end=end)
    else:
        print(msg, end=end)


def human_size(n: float) -> str:
    """Format bytes as B/KB/MB/GB/TB (matches dh.fsz)."""
    sign = "-" if n < 0 else ""
    n = abs(float(n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{sign}{n:.2f}{unit}"
        n /= 1024
    return f"{sign}{n:.2f}TB"


def path_size(p: Path | str) -> int:
    """Total bytes of a file or a directory tree (matches dh.gsz)."""
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    if not p.is_dir():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def find_files(root: Path | str, extensions: Sequence[str]) -> list[Path]:
    """Recursively find files ending with any of the extensions."""
    root = Path(root)
    exts = tuple(e.lower() for e in extensions)
    if root.is_file():
        return [root] if any(root.name.lower().endswith(e) for e in exts) else []
    if not root.is_dir():
        return []
    return sorted(
        f for f in root.rglob("*")
        if f.is_file() and any(f.name.lower().endswith(e) for e in exts)
    )


def run_cmd(
    cmd: Sequence[str],
    show_output: bool = False,
    timeout: Optional[int] = None,
    **kw: Any,
) -> tuple[int, str, str]:
    """Run a subprocess, returning (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True,
            timeout=timeout, **kw,
        )
        if show_output and proc.stdout:
            print(proc.stdout, end="")
        if show_output and proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timeout: {exc}"


def read_package_list(path: Path | str) -> list[str]:
    """Read one package per line, skipping blanks and '#'-comments."""
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: file '{path}' not found.", file=sys.stderr)
        return []
    except OSError as exc:
        print(f"Error reading file: {exc}", file=sys.stderr)
        return []
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def default_workers() -> int:
    """min(max(1, cpu//2), 8) — matches pure_pypkg_reinstaller.py."""
    return min(max(1, (os.cpu_count() or 2) // 2), 8)


def parallel_map(
    func: Callable[[Any], Any],
    items: Sequence[Any],
    workers: int,
) -> list[Any]:
    """Map ``func`` over ``items`` using a process pool (or sequentially)."""
    if not items:
        return []
    if workers <= 1 or len(items) == 1:
        return [func(i) for i in items]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(func, items))


def fuzzy_partial_ratio(query: str, candidate: str) -> float:
    """Partial-ratio score 0-100; rapidfuzz if available, else difflib."""
    if _rapidfuzz is not None:
        return float(_rapidfuzz.partial_ratio(query, candidate))
    import difflib
    return difflib.SequenceMatcher(None, query, candidate).ratio() * 100.0


def confirm(prompt: str) -> bool:
    """Yes/no prompt; returns True on y/yes."""
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


# ============================================================================
# pip interface (subprocess backend + in-process `pip._internal` backend)
# ============================================================================
def pip_run_subprocess(args: Sequence[str], timeout: Optional[int] = None) -> tuple[int, str, str]:
    """Run ``python -m pip <args>`` in a subprocess."""
    return run_cmd([sys.executable, "-m", "pip", *args], timeout=timeout)


def pip_run_api(args: Sequence[str]) -> tuple[int, str, str]:
    """
    Run pip in-process via ``pip._internal.cli.main``, capturing stdout/stderr.
    Returns ``(returncode, stdout, stderr)``.
    """
    try:
        from pip._internal.cli.main import main as pip_main  # type: ignore
    except ImportError as exc:
        return 1, "", f"pip._internal not available: {exc}"

    old_out, old_err = sys.stdout, sys.stderr
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        sys.stdout, sys.stderr = out_buf, err_buf
        try:
            rc = pip_main(list(args))
        except SystemExit as exc:
            rc = int(exc.code) if exc.code not in (None, 0) else 0
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return int(rc), out_buf.getvalue(), err_buf.getvalue()


def pip_run(args: Sequence[str], backend: str, timeout: Optional[int] = None) -> tuple[int, str, str]:
    """Dispatch to the chosen pip backend."""
    if backend == "api":
        return pip_run_api(args)
    return pip_run_subprocess(args, timeout=timeout)


# ============================================================================
# Subcommand 1: apt-install  (aptin.py)
# ============================================================================
def _apt_list_all() -> list[str]:
    """Return every package name known to pkg/apt (matches aptin.py)."""
    rc, out, _ = run_cmd(["pkg", "list-all"])
    if rc == 0:
        names: list[str] = []
        for line in out.split("\n"):
            if not line or line.startswith("Listing") or line.startswith("Packages"):
                continue
            head = line.split("/")[0].split()
            if head:
                names.append(head[0])
        return names

    rc, out, _ = run_cmd(["apt", "list", "--installed"])
    if rc == 0:
        return [line.split("/")[0] for line in out.split("\n") if "/" in line]
    return []


def _wildcard_to_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(
        pattern.replace("*", ".*").replace("?", "."),
        re.IGNORECASE,
    )


def cmd_apt_install(args: argparse.Namespace) -> int:
    """Search apt/pkg by wildcard, confirm, and install."""
    print(f"Searching for packages matching '{args.pattern}'...")
    rx = _wildcard_to_regex(args.pattern)
    matches = [p for p in _apt_list_all() if rx.search(p)]
    if not matches:
        print(f"No packages found matching pattern '{args.pattern}'")
        return 0
    print(f"\nFound {len(matches)} package(s) to install:")
    for p in matches:
        print(f"- {p}")
    if not args.no_confirm and not confirm("\nDo you want to install these packages? (y/N): "):
        print("Installation cancelled.")
        return 0
    rc, _, err = run_cmd(["pkg", "install", *matches], show_output=True)
    if rc == 0:
        cprint("\n✓ Installation completed successfully!", "green")
        return 0
    cprint(f"\n✗ Installation failed: {err}", "red")
    return 1


# ============================================================================
# Subcommand 2: apt-reinstall  (system_pkg_reinstaller.py)
# ============================================================================
def _apt_reinstall_one(pkg: str) -> bool:
    print(f"Reinstalling: {pkg}")
    rc, _, err = run_cmd(["apt", "install", "--reinstall", "-y", pkg], show_output=True)
    if rc == 0:
        cprint(f"✓ Successfully reinstalled: {pkg}", "green")
        return True
    cprint(f"✗ Failed to reinstall {pkg}", "red")
    if err:
        print(f"  Error: {err.strip()}")
    return False


def cmd_apt_reinstall(args: argparse.Namespace) -> int:
    """Sequentially reinstall every apt package listed in a file."""
    path = Path(args.file).expanduser()
    print(f"Reading packages from: {path}")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Warning: this usually requires root for apt.")
    pkgs = read_package_list(path)
    if not pkgs:
        print("No packages found in file.")
        return 0
    print(f"Found {len(pkgs)} package(s) to reinstall.")
    print("-" * 40)
    ok = fail = 0
    for p in pkgs:
        if _apt_reinstall_one(p):
            ok += 1
        else:
            fail += 1
        print()
    print("-" * 40)
    print(f"Summary: {ok} successful, {fail} failed")
    return 0 if fail == 0 else 1


# ============================================================================
# Subcommand 3: wheel-install  (install_wheels.py)
# ============================================================================
_PLATFORM_EXTS = (".so", ".pyd", ".dll", ".dylib")
_WHEEL_META_SUFFIXES = (".dist-info/WHEEL", ".dist-info/METADATA")


def is_pure_wheel(path: Path) -> bool:
    """
    Heuristic matching install_wheels.py: a wheel is "pure" if its name
    contains ``-none-any`` or its METADATA/WHEEL declares
    ``Root-Is-Purelib: true`` (and does not say false).
    """
    if "-none-any" in path.stem:
        return True
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(_WHEEL_META_SUFFIXES):
                    try:
                        text = zf.open(name).read().decode("utf-8", errors="replace")
                    except OSError:
                        continue
                    if "Root-Is-Purelib:true" in text.replace(" ", ""):
                        return True
                    if "Root-Is-Purelib:false" in text.replace(" ", ""):
                        return False
    except (zipfile.BadZipFile, OSError):
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(_PLATFORM_EXTS):
                    return False
        return True
    except (zipfile.BadZipFile, OSError):
        return False


def describe_wheel(path: Path) -> str:
    """Human label for a wheel's platform specificity."""
    stem = path.stem
    parts = stem.split("-")
    if "none-any" in stem:
        return "Pure Python (any platform)"
    if len(parts) >= 4:
        tag = parts[-1]
        low = tag.lower()
        if "android" in low:
            return f"Android-specific ({tag})"
        if "linux" in low:
            return f"Linux-specific ({tag})"
        return f"Platform-specific ({tag})"
    return "Unknown"


def _install_one_wheel(arg: tuple[str, bool]) -> tuple[str, bool, str]:
    """Worker: install one wheel. ``arg`` = (path_str, is_pure)."""
    path_str, is_pure = arg
    cmd = [sys.executable, "-m", "pip", "install"]
    if is_pure:
        cmd.insert(3, "--user")
    cmd.append(path_str)
    rc, _, err = run_cmd(cmd)
    target = "user site-packages" if is_pure else "system site-packages"
    if rc == 0:
        return path_str, True, f"✓ {Path(path_str).name} -> {target}"
    return path_str, False, f"✗ {Path(path_str).name}: {err.strip() or 'pip failed'}"


def cmd_wheel_install(args: argparse.Namespace) -> int:
    """Install every *.whl in a directory, choosing user vs system per wheel."""
    root = Path(args.directory).resolve()
    wheels = sorted(root.glob("*.whl"))
    if not wheels:
        print(f"No .whl files found in {root}.")
        return 0
    print(f"Found {len(wheels)} wheel(s) in {root}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    print("-" * 40)
    plan: list[tuple[str, bool]] = []
    for w in wheels:
        pure = is_pure_wheel(w)
        print(f"Analyzing: {w.name}")
        print(f"  Type:   {describe_wheel(w)}")
        print(f"  Target: {'USER site-packages' if pure else 'SYSTEM site-packages'}")
        plan.append((str(w), pure))
    print("=" * 40)
    print("Starting parallel installation...")
    results = parallel_map(_install_one_wheel, plan, workers=args.workers)
    successes, failures = [], []
    for _, ok, msg in results:
        print(msg)
        (successes if ok else failures).append(msg)
    print("=" * 40)
    print("INSTALLATION SUMMARY")
    print("-" * 40)
    print(f"Total wheels: {len(wheels)}")
    cprint(f"✓ Successfully installed: {len(successes)}", "green")
    if failures:
        cprint(f"✗ Failed: {len(failures)}", "red")
        for m in failures:
            print(f"  {m}")
    print("Done!")
    return 0 if not failures else 1


# ============================================================================
# Subcommand 4: wheel-install-local  (piu.py)
# ============================================================================
def cmd_wheel_install_local(args: argparse.Namespace) -> int:
    """Install local wheel paths with pip, optionally deleting them after."""
    pip_args: list[str] = ["install"]
    if not args.no_user:
        pip_args.append("--user")
    if not args.with_deps:
        pip_args.append("--no-deps")
    if args.no_compile:
        pip_args.append("--no-compile")
    pip_args.extend(str(Path(p)) for p in args.wheels)

    rc, _, err = run_cmd([sys.executable, "-m", "pip", *pip_args], show_output=True)
    if rc != 0:
        cprint(f"✗ pip install failed: {err.strip()}", "red")
        return 1

    if not args.keep_file:
        for p in args.wheels:
            fp = Path(p)
            if fp.exists():
                fp.unlink()
                print(f"{fp.name} removed")
    return 0


# ============================================================================
# Subcommand 5: wheel-move-installed  (move_installed_wheels.py)
# ============================================================================
DEFAULT_WHEEL_EXCLUDES: tuple[str, ...] = (
    "pybind11", "dh", "pip", "setuptools", "wheel", "packaging",
    "importlib_metadata", "importlib_resources", "pkginfo",
    "scikit_build_core", "setuptools_scm", "setuptools_rust",
)


def _installed_versions() -> dict[str, Any]:
    """Map normalized distribution name -> Version."""
    out: dict[str, Any] = {}
    for dist in _im.distributions():
        try:
            name = dist.metadata["Name"]
            ver = dist.version
        except (KeyError, AttributeError):
            continue
        if name and Version is not None:
            out[name.lower().replace("-", "_")] = Version(ver)
    return out


def cmd_wheel_move_installed(args: argparse.Namespace) -> int:
    """Move matched wheels to ``dst`` and invalid ones to ``invalid``."""
    if parse_wheel_filename is None or Version is None:
        print("Error: 'packaging' is required for this subcommand.",
              file=sys.stderr)
        return 1
    if not args.allow_system and sys.prefix == sys.base_prefix:
        print("⚠ Not running inside a virtual environment.", file=sys.stderr)
        return 1

    src, dst, invalid = Path(args.src), Path(args.dst), Path(args.invalid)
    dst.mkdir(parents=True, exist_ok=True)
    invalid.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        print(f"Directory not found: {src}")
        return 0

    installed = _installed_versions()
    excludes = set(args.exclude)
    removed = 0
    for whl in src.rglob("*.whl"):
        try:
            dist, ver, *_ = parse_wheel_filename(whl.name)
        except Exception as exc:
            print(f"[ERROR] {whl.name}: {exc}")
            shutil.move(str(whl), invalid / whl.name)
            continue
        key = dist.lower().replace("-", "_")
        if key in excludes:
            print(f"[EXCLUDED] {dist}=={ver} → skipped")
            continue
        if key in installed:
            current = installed[key]
            if current == Version(str(ver)):
                cprint(f"[MATCH] {dist}=={ver} → removing", "cyan")
                whl.unlink()
                removed += 1
            else:
                whl.unlink()
                removed += 1
                print(f"[DIFF VERSION] {dist} (installed {current}, wheel {ver}) -> removed")
    print(f"\nDone. Removed {removed} wheel(s).")
    return 0


# ============================================================================
# Subcommand 6: pip-uninstall  (piprm.py + pu.py merged)
# ============================================================================
def _list_installed_packages() -> list[str]:
    """Return every installed distribution name via ``pip freeze``."""
    rc, out, _ = run_cmd([sys.executable, "-m", "pip", "freeze"])
    if rc != 0:
        return []
    pkgs: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkgs.append(re.split(r"[=<>!]", line, 1)[0].strip())
    return pkgs


def _cached_installed_list(cache_file: Path, max_age: float) -> list[str]:
    """Return cached installed list; refresh if stale or missing."""
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < max_age:
        return [l.strip() for l in cache_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    fresh = _list_installed_packages()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("\n".join(fresh), encoding="utf-8")
    return fresh


def cmd_pip_uninstall(args: argparse.Namespace) -> int:
    """Fuzzy-match installed packages against a prefix and uninstall them."""
    pattern = args.pattern.lower()
    cache = Path(args.cache_file)
    installed = _cached_installed_list(cache, max_age=float(args.cache_max_age))
    if not installed:
        print("No installed packages could be enumerated.")
        return 1

    matches = [
        name for name in installed
        if pattern in name.lower()
        or fuzzy_partial_ratio(pattern, name.lower()) > args.fuzzy_threshold
    ]
    if not matches:
        print("no match found")
        return 0

    backend = args.backend
    for pkg in matches:
        if not args.no_confirm and not confirm(f"remove {pkg} --> ? (y/n) "):
            continue
        if backend == "api":
            rc, _, err = pip_run_api(["uninstall", "-y", pkg])
        else:
            rc, _, err = pip_run_subprocess(["uninstall", "-y", pkg])
        if rc == 0:
            print(f"Uninstalled {pkg}")
        else:
            print(f"Skipped {pkg} (not installed or error): {err.strip()}")
    return 0


# ============================================================================
# Subcommand 7: pip-uninstall-flake8  (rm_flake8_plugins.py)
# ============================================================================
_FLAKE8_GROUPS = ("flake8.extension", "flake8.report")
_FLAKE8_NAME_RX = re.compile(r"^flake8-", re.IGNORECASE)


def _find_flake8_plugins() -> list[str]:
    """Distributions that expose flake8 entry points or start with 'flake8-'."""
    found: set[str] = set()
    for dist in _im.distributions():
        try:
            name = dist.metadata["Name"] or ""
        except (KeyError, AttributeError):
            continue
        try:
            eps = list(dist.entry_points)
        except Exception:
            eps = []
        if any(getattr(ep, "group", "") in _FLAKE8_GROUPS for ep in eps):
            found.add(name)
            continue
        if _FLAKE8_NAME_RX.match(name):
            found.add(name)
    return sorted(found)


def cmd_pip_uninstall_flake8(args: argparse.Namespace) -> int:
    """Uninstall every detected flake8 plugin."""
    print("Scanning for flake8 plugins...")
    plugins = _find_flake8_plugins()
    if args.keep_flake8:
        plugins = [p for p in plugins if p.lower() != "flake8"]
    if not plugins:
        print("No flake8 plugins found to uninstall.")
        return 0
    print(f"\nFound {len(plugins)} flake8 plugin(s) to uninstall:")
    for p in plugins:
        print(f"- {p}")
    if args.dry_run:
        print("\nDry run mode — no packages will be uninstalled.")
        return 0
    if not args.no_confirm and not confirm("\nDo you want to proceed with uninstallation? (yes/no): "):
        print("Uninstallation cancelled.")
        return 0
    fail = 0
    for p in plugins:
        print(f"\nUninstalling {p}...")
        rc, _, err = pip_run_subprocess(["uninstall", "-y", p])
        if rc == 0:
            cprint(f"✓ Successfully uninstalled {p}", "green")
        else:
            cprint(f"✗ Failed to uninstall {p}: {err}", "red")
            fail += 1
    return 0 if fail == 0 else 1


# ============================================================================
# Subcommand 8: pip-reinstall-list  (pure_pypkg_reinstaller.py)
# ============================================================================
def _reinstall_one_subprocess(arg: tuple[str, str, int, bool, bool]) -> tuple[str, bool, str]:
    """
    Worker for pip-reinstall-list. ``arg`` = (pkg, pip_cmd, timeout, with_deps, dry).
    """
    pkg, pip_cmd, timeout, with_deps, dry = arg
    cmd = [pip_cmd, "install", "--force-reinstall", "--upgrade"]
    if not with_deps:
        cmd.append("--no-deps")
    cmd.append(pkg)
    if dry:
        return pkg, True, f"[DRY RUN] Would run: {' '.join(cmd)}"
    print(f"Reinstalling: {pkg}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return pkg, False, "Timeout"
    except Exception as exc:  # noqa: BLE001
        return pkg, False, str(exc)
    if proc.returncode == 0:
        return pkg, True, "OK"
    err = (proc.stderr or proc.stdout).strip()
    return pkg, False, err[:200]


def cmd_pip_reinstall_list(args: argparse.Namespace) -> int:
    """Reinstall every package listed in a file, in parallel."""
    path = Path(args.file).expanduser()
    print(f"Reading packages from: {path}")
    print(f"Using {args.workers} parallel workers")
    if args.dry_run:
        print("DRY RUN MODE — no packages will be installed")
    print("-" * 40)

    pip_cmd = args.pip_cmd
    if shutil.which(pip_cmd) is None and shutil.which("pip") is None:
        print("Error: pip is not installed or not found in PATH")
        return 1
    if shutil.which(pip_cmd) is None:
        pip_cmd = "pip"

    pkgs = read_package_list(path)
    if not pkgs:
        print("No packages found in file.")
        return 0
    print(f"Found {len(pkgs)} package(s) to reinstall.")
    print("-" * 40)

    plan = [(p, pip_cmd, args.timeout, args.with_deps, args.dry_run) for p in pkgs]
    results = parallel_map(_reinstall_one_subprocess, plan, workers=args.workers)
    ok = fail = 0
    failed_names: list[str] = []
    for pkg, success, msg in results:
        if success:
            ok += 1
        else:
            fail += 1
            failed_names.append(pkg)
        if not args.dry_run:
            print(f"{'✓' if success else '✗'} {pkg}: {msg[:120]}")
    print("\n" + "=" * 40)
    print(f"Summary: {ok} successful, {fail} failed")
    if failed_names:
        print("\nFailed packages:")
        for p in failed_names:
            print(f"- {p}")
    return 0 if fail == 0 else 1


# ============================================================================
# Subcommand 9: pip-reinstall-pypi  (pure_teinstaller.py)
# ============================================================================
def _pypi_exists(name: str, timeout: int = 5) -> bool:
    url = f"https://pypi.org/pypi/{name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "pkgtool/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return False


def _reinstall_pypi_one(arg: tuple[str, bool, bool]) -> tuple[str, bool]:
    """Worker: reinstall one package from PyPI. ``arg`` = (pkg, with_deps, skip_check)."""
    pkg, with_deps, skip_check = arg
    if not skip_check and not _pypi_exists(pkg):
        print(f"[SKIP] '{pkg}' not found on PyPI.")
        return pkg, False
    print(f"[INSTALLING] {pkg}...")
    cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall"]
    if not with_deps:
        cmd.append("--no-deps")
    cmd.append(pkg)
    rc, _, _ = run_cmd(cmd)
    if rc == 0:
        print(f"[SUCCESS] Re-installed {pkg}")
        return pkg, True
    print(f"[FAIL] Could not reinstall {pkg}")
    return pkg, False


def cmd_pip_reinstall_pypi(args: argparse.Namespace) -> int:
    """Reinstall PyPI packages from a list file, pruning successes in place."""
    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"{path} not found.")
        return 1
    names = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not names:
        print(f"{path} is empty.")
        return 0

    remaining = set(names)
    pending: list[str] = list(names)
    while pending:
        batch = pending[: args.batch_size]
        pending = pending[args.batch_size :]
        plan = [(n, args.with_deps, args.skip_pypi_check) for n in batch]
        results = parallel_map(_reinstall_pypi_one, plan, workers=args.workers)
        for pkg, ok in results:
            if ok:
                remaining.discard(pkg)
        # Rewrite file after each batch (matches original behavior).
        text = "\n".join(sorted(remaining))
        path.write_text(text + ("\n" if text else ""), encoding="utf-8")

    print(f"Done! Remaining in {path.name}: {len(remaining)}")
    return 0


# ============================================================================
# Subcommand 10: pip-reinstall-entry-points  (reinstaller.py)
# ============================================================================
def _dist_entry_point_groups(dist: Any) -> set[str]:
    """Best-effort set of entry-point groups exposed by a distribution."""
    try:
        eps = dist.entry_points
    except Exception:
        return set()
    if not eps:
        return set()
    groups: set[str] = set()
    if hasattr(eps, "select"):
        try:
            groups.update(eps.groups)
        except Exception:
            groups.update(getattr(ep, "group", "") for ep in eps)
    else:
        groups.update(getattr(ep, "group", "") for ep in eps)
    return {g for g in groups if g}


def _packages_with_entry_points(excludes: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for dist in _im.distributions():
        try:
            name = dist.metadata["Name"]
        except (KeyError, AttributeError):
            continue
        if not name or name in excludes:
            continue
        groups = _dist_entry_point_groups(dist)
        if not groups:
            continue
        found[name] = {
            "version": dist.version or "Unknown",
            "summary": (dist.metadata.get("Summary") or "No summary"),
            "groups": sorted(groups),
        }
    return found


def _reinstall_one_api(arg: tuple[str, bool]) -> tuple[str, bool, str]:
    """Reinstall a single package via pip._internal. ``arg`` = (pkg, with_deps)."""
    pkg, with_deps = arg
    cmd = ["install", "--force-reinstall", "--no-cache-dir"]
    if not with_deps:
        cmd.append("--no-deps")
    cmd.append(pkg)
    rc, _, err = pip_run_api(cmd)
    if rc == 0:
        return pkg, True, "Successfully reinstalled"
    return pkg, False, (err or "pip error").strip()[:200]


def _prompt_reinstall(pkg: str, info: dict[str, Any], with_deps: bool) -> str:
    print("\n" + "=" * 40)
    print(f"📦 Package: {pkg}")
    print(f"   Version: {info['version']}")
    print(f"   Entry points: {','.join(info['groups'])}")
    if info["summary"] != "No summary":
        print(f"   Summary: {info['summary']}")
    if with_deps:
        print("   ⚠️  Will reinstall dependencies (may cause conflicts)")
    print("-" * 40)
    while True:
        try:
            ans = input("Reinstall this package? (y/n/a/?) [y/n/a/?]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "no"
        if ans in ("y", "yes"):
            return "yes"
        if ans in ("n", "no"):
            return "no"
        if ans in ("a", "all"):
            return "all"
        if ans in ("?", "help"):
            print("  y — reinstall this one")
            print("  n — skip")
            print("  a — yes to all remaining")
            print("  ? — this help")
            continue
        print("Invalid response.")


def cmd_pip_reinstall_entry_points(args: argparse.Namespace) -> int:
    """Reinstall every installed distribution that provides entry points."""
    excludes = set(args.exclude)
    all_pkgs = _packages_with_entry_points(excludes)
    if not all_pkgs:
        print("No packages with entry points found!")
        return 0

    targets = set(all_pkgs)
    if args.only:
        targets &= set(args.only)
    targets = {n for n in targets if n not in excludes}

    print(f"Found {len(all_pkgs)} packages with entry points")
    print(f"Will reinstall {len(targets)} packages after filtering")
    if targets:
        print("\nPackages with entry points:")
        for i, name in enumerate(sorted(targets), 1):
            info = all_pkgs[name]
            print(f"  {i:3d}. {name} (v{info['version']}) — "
                  f"entry points: {','.join(info['groups'])}")

    if args.dry_run:
        print("\nDRY RUN — no packages will be reinstalled")
        return 0
    if not targets:
        print("No packages to reinstall after filtering!")
        return 0

    selected = set(targets)
    if not args.yes:
        chosen: set[str] = set()
        auto_all = False
        for name in sorted(targets):
            if auto_all:
                chosen.add(name)
                continue
            ans = _prompt_reinstall(name, all_pkgs[name], args.include_deps)
            if ans == "all":
                auto_all = True
                chosen.add(name)
            elif ans == "yes":
                chosen.add(name)
        selected = chosen
        if not selected:
            print("No packages selected for reinstallation!")
            return 0
    else:
        print("Skipping confirmation — will reinstall all packages")

    print(f"\nStarting reinstallation of {len(selected)} selected packages...")
    plan = [(n, args.include_deps) for n in sorted(selected)]
    results = parallel_map(_reinstall_one_api, plan, workers=args.workers)

    successes = [n for n, ok, _ in results if ok]
    failures = [(n, msg) for n, ok, msg in results if not ok]

    print("\n" + "=" * 40)
    print("REINSTALLATION SUMMARY")
    print("=" * 40)
    cprint(f"✓ Successfully reinstalled: {len(successes)}", "green")
    if failures:
        cprint(f"✗ Failed to reinstall: {len(failures)}", "red")
        for name, msg in failures:
            print(f"  ✗ {name}: {msg[:100]}")
    return 0 if not failures else 1


# ============================================================================
# CLI parser
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pkgtool.py",
        description="Unified package-management toolkit (apt + pip + wheels).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---- apt-install ------------------------------------------------------
    a = sub.add_parser("apt-install",
                       help="Wildcard-install apt/pkg packages (aptin.py).")
    a.add_argument("pattern", help="Wildcard pattern (* and ? supported).")
    a.add_argument("-y", "--no-confirm", action="store_true",
                   help="Skip the confirmation prompt.")
    a.set_defaults(func=cmd_apt_install)

    # ---- apt-reinstall ----------------------------------------------------
    b = sub.add_parser("apt-reinstall",
                       help="Reinstall apt packages from a list file.")
    b.add_argument("file", nargs="?", default=str(Path.home() / "missing.txt"),
                   help="Path to the package list (default: ~/missing.txt).")
    b.set_defaults(func=cmd_apt_reinstall)

    # ---- wheel-install ----------------------------------------------------
    c = sub.add_parser("wheel-install",
                       help="Install every *.whl in a directory.")
    c.add_argument("--dir", dest="directory", default=".",
                   help="Directory containing wheels (default: .).")
    c.add_argument("-j", "--workers", type=int, default=8,
                   help="Parallel workers (default: 8).")
    c.set_defaults(func=cmd_wheel_install)

    # ---- wheel-install-local ---------------------------------------------
    d = sub.add_parser("wheel-install-local",
                       help="Install local wheel files (piu.py).")
    d.add_argument("wheels", nargs="+", help="One or more .whl paths.")
    d.add_argument("--no-user", action="store_true",
                   help="Do NOT pass --user to pip.")
    d.add_argument("--with-deps", action="store_true",
                   help="Allow pip to install dependencies.")
    d.add_argument("--no-compile", action="store_true", default=True,
                   help="Pass --no-compile (default: True).")
    d.add_argument("--keep-file", action="store_true",
                   help="Keep the wheel file after installing (default: delete).")
    d.set_defaults(func=cmd_wheel_install_local)

    # ---- wheel-move-installed --------------------------------------------
    e = sub.add_parser("wheel-move-installed",
                       help="Sort wheels matching installed dists.")
    e.add_argument("--src", default="/sdcard/whl",
                   help="Source directory (default: /sdcard/whl).")
    e.add_argument("--dst", default="/sdcard/installed",
                   help="Where matching wheels go (default: /sdcard/installed).")
    e.add_argument("--invalid", default="/sdcard/invalid",
                   help="Where invalid wheels go (default: /sdcard/invalid).")
    e.add_argument("--exclude", nargs="+", default=list(DEFAULT_WHEEL_EXCLUDES),
                   help="Distributions to leave alone.")
    e.add_argument("--allow-system", action="store_true",
                   help="Allow running outside a virtualenv.")
    e.set_defaults(func=cmd_wheel_move_installed)

    # ---- pip-uninstall ----------------------------------------------------
    f = sub.add_parser("pip-uninstall",
                       help="Fuzzy-uninstall installed packages by prefix.")
    f.add_argument("pattern", help="Prefix / substring to match.")
    f.add_argument("-b", "--backend", choices=("subprocess", "api"),
                   default="subprocess",
                   help="pip backend (default: subprocess).")
    f.add_argument("--no-confirm", action="store_true",
                   help="Do not prompt per package.")
    f.add_argument("--cache-file", default="/sdcard/data/pip.list",
                   help="Path to the cached pip-freeze list.")
    f.add_argument("--cache-max-age", type=float, default=57600.0,
                   help="Seconds before refreshing the cache (default: 57600).")
    f.add_argument("--fuzzy-threshold", type=int, default=95,
                   help="Minimum partial_ratio score (default: 95).")
    f.set_defaults(func=cmd_pip_uninstall)

    # ---- pip-uninstall-flake8 --------------------------------------------
    g = sub.add_parser("pip-uninstall-flake8",
                       help="Uninstall every flake8 plugin.")
    g.add_argument("--dry-run", action="store_true",
                   help="Show what would be removed without removing it.")
    g.add_argument("--no-confirm", action="store_true",
                   help="Skip the confirmation prompt.")
    g.add_argument("--keep-flake8", action="store_true", default=True,
                   help="Exclude the flake8 package itself (default: True).")
    g.set_defaults(func=cmd_pip_uninstall_flake8)

    # ---- pip-reinstall-list ----------------------------------------------
    h = sub.add_parser("pip-reinstall-list",
                       help="Reinstall packages from a list file (parallel).")
    h.add_argument("file", nargs="?", default=str(Path.home() / "missing.txt"),
                   help="Path to the package list (default: ~/missing.txt).")
    h.add_argument("-j", "--workers", type=int, default=default_workers(),
                   help="Parallel workers (default: cpu//2, capped at 8).")
    h.add_argument("--dry-run", action="store_true",
                   help="Print commands but do not run them.")
    h.add_argument("--with-deps", action="store_true",
                   help="Allow pip to resolve dependencies.")
    h.add_argument("--timeout", type=int, default=300,
                   help="Per-package pip timeout in seconds (default: 300).")
    h.add_argument("--pip-cmd", default="pip3",
                   help="pip executable to use (default: pip3).")
    h.set_defaults(func=cmd_pip_reinstall_list)

    # ---- pip-reinstall-pypi ----------------------------------------------
    i = sub.add_parser("pip-reinstall-pypi",
                       help="Reinstall PyPI packages and prune successes.")
    i.add_argument("file", nargs="?", default="pure.txt",
                   help="List file (default: pure.txt).")
    i.add_argument("-j", "--workers", type=int, default=8,
                   help="Parallel workers (default: 8).")
    i.add_argument("--batch-size", type=int, default=8,
                   help="Batch size between list-file rewrites (default: 8).")
    i.add_argument("--with-deps", action="store_true",
                   help="Allow pip to resolve dependencies.")
    i.add_argument("--skip-pypi-check", action="store_true",
                   help="Do not pre-check PyPI for existence.")
    i.set_defaults(func=cmd_pip_reinstall_pypi)

    # ---- pip-reinstall-entry-points --------------------------------------
    j = sub.add_parser("pip-reinstall-entry-points",
                       help="Reinstall every dist with entry points.")
    j.add_argument("-e", "--exclude", nargs="+",
                   default=["pip", "setuptools", "wheel"],
                   help="Packages to skip (default: pip setuptools wheel).")
    j.add_argument("-o", "--only", nargs="+",
                   help="Only reinstall the listed packages.")
    j.add_argument("--dry-run", action="store_true",
                   help="Print the plan and exit.")
    j.add_argument("--include-deps", action="store_true",
                   help="Also reinstall dependencies (risky).")
    j.add_argument("-y", "--yes", action="store_true",
                   help="Skip interactive confirmation.")
    j.add_argument("-j", "--workers", type=int, default=8,
                   help="Parallel workers (default: 8).")
    j.add_argument("-v", "--verbose", action="store_true",
                   help="More verbose output.")
    j.set_defaults(func=cmd_pip_reinstall_entry_points)

    return p


# ============================================================================
# Entry point
# ============================================================================
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
