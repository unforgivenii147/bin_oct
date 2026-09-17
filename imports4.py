#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dh import PKG_MAPPING, STDLIB

SKIP_DIRS = {
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "build",
    "dist",
    ".eggs",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}
SKIP_FILES = {"setup.py", "conftest.py", "__init__.py"}
PKG_BLOCKLIST = {
    "pip",
    "setuptools",
    "wheel",
    "distribute",
    "easy_install",
    "apt",
    "apt_pkg",
    "gi",
    "dbus",
    "__future__",
    "__main__",
    "__init__",
    "a",
    "an",
    "the",
    "each",
    "every",
    "known",
    "various",
    "statements",
    "in",
    "of",
    "and",
    "or",
    "is",
    "it",
    "that",
    "are",
}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize(name):
    return name.lower().replace("_", "-")


def is_valid_module_name(name):
    if not name or not _IDENT_RE.match(name):
        return False
    return not (name.startswith("__") and name.endswith("__"))


PKG_MAP_NORM = {normalize(k): v for k, v in PKG_MAPPING.items()}
STDLIB_NORM = {normalize(m) for m in STDLIB} | {"__future__"}
BLOCKLIST_NORM = {normalize(m) for m in PKG_BLOCKLIST}


def load_pypi_packages(path="/sdcard/data/pip.txt"):
    pypi = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            pypi.add(normalize(name))
    return pypi


def get_installed_packages(pip_version="pip"):
    installed_with_versions = []
    installed = set()
    try:
        stdout, _ = subprocess.Popen(
            [pip_version, "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).communicate()
    except FileNotFoundError:
        print(f"[!] '{pip_version}' not found, skipping installed-package check")
        return installed_with_versions, installed
    for raw in stdout.splitlines():
        line = raw.decode("utf-8").strip()
        if not line or line.startswith(("#", "-e")):
            continue
        installed_with_versions.append(line)
        name = line.split("==")[0].split("@")[0].strip()
        installed.add(normalize(name))
    return installed_with_versions, installed


def get_local_modules(directory):
    local = set()
    root = Path(directory).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and not d.endswith(".egg-info")
            and not d.startswith(".")
        ]
        if "__init__.py" in filenames:
            local.add(normalize(dirpath.name))
        for fn in filenames:
            if fn.endswith(".py") and fn not in SKIP_FILES:
                local.add(normalize(fn[:-3]))
    if root.name and root.name not in {".", "/", ""}:
        local.add(normalize(root.name))
    return local


def extract_imports_from_source(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module:
                yield node.module.split(".")[0]


def get_project_imports(directory=os.curdir):
    modules = []
    seen = set()
    for root, dirnames, files in os.walk(directory):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for name in files:
            full = os.path.join(root, name)
            if name.endswith(".py"):
                try:
                    source = Path(full).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for mod in extract_imports_from_source(source):
                    if mod not in seen:
                        seen.add(mod)
                        modules.append(mod)
                        print(f"found {mod} in {name}")
            elif name.endswith(".ipynb"):
                try:
                    contents = json.loads(
                        Path(full).absolute().read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    continue
                for cell in contents.get("cells", []):
                    if cell.get("cell_type") != "code":
                        continue
                    src = "".join(cell.get("source", []))
                    for mod in extract_imports_from_source(src):
                        if mod not in seen:
                            seen.add(mod)
                            modules.append(mod)
                            print(f"found {mod} in {name}")
    return modules


def resolve_package_name(import_name):
    norm = normalize(import_name)
    mapped = PKG_MAP_NORM.get(norm)
    if mapped and normalize(mapped) != norm:
        return mapped, True
    return import_name, False


def init(args):
    pypi_index = load_pypi_packages(args["pypi_list"])
    print("[i] Loaded {} packages from {}".format(len(pypi_index), args["pypi_list"]))
    print(f"[i] Loaded {len(PKG_MAP_NORM)} import->package mappings")
    target = args["path"] if args["path"] else os.curdir
    local_modules = get_local_modules(target)
    print(f"[i] Detected {len(local_modules)} local modules/packages")
    modules = get_project_imports(target)
    print(f"[i] Found {len(modules)} unique imports in source")
    pip_cmd = args["version"] if args["version"] else "pip3"
    _, installed = get_installed_packages(pip_cmd)
    print(f"[i] {len(installed)} packages installed locally")
    output_text = []
    skipped_stdlib = []
    skipped_installed = []
    skipped_local = []
    skipped_invalid = []
    missing = []
    mapped_count = 0
    for mod in modules:
        norm = normalize(mod)
        if not is_valid_module_name(mod):
            skipped_invalid.append(mod)
            continue
        if norm in BLOCKLIST_NORM:
            skipped_invalid.append(mod)
            continue
        if norm in STDLIB_NORM:
            skipped_stdlib.append(mod)
            continue
        if norm in local_modules:
            skipped_local.append(mod)
            continue
        pkg_name, was_mapped = resolve_package_name(mod)
        pkg_norm = normalize(pkg_name)
        if pkg_norm in installed or norm in installed:
            skipped_installed.append(mod)
            continue
        if pkg_norm in pypi_index:
            if was_mapped:
                mapped_count += 1
                print(f"[→] {mod} -> {pkg_name}")
                output_text.append(pkg_name)
            else:
                output_text.append(mod)
        elif norm in pypi_index:
            output_text.append(mod)
        else:
            missing.append(mod)
    print(f"\n[i] Skipped {len(skipped_stdlib)} stdlib modules")
    print(f"[i] Skipped {len(skipped_local)} local modules")
    print(f"[i] Skipped {len(skipped_installed)} already-installed modules")
    print(f"[i] Skipped {len(skipped_invalid)} invalid/blocklisted names")
    if skipped_invalid:
        preview = ", ".join(sorted(set(skipped_invalid))[:15])
        if len(set(skipped_invalid)) > 15:
            preview += " ..."
        print(f"    {preview}")
    print(f"[i] Resolved {mapped_count} renamed packages")
    if missing:
        print(
            "[i] Skipped {} unknown modules: {}".format(
                len(missing), ", ".join(sorted(missing))
            )
        )
    unique = sorted(set(output_text))
    if args.get("dry_run"):
        print(f"\n[dry-run] Would write {len(unique)} packages to requirements.txt:")
        for pkg in unique:
            print("  " + pkg)
        return
    out_dir = args["path"] if args["path"] else os.curdir
    out_file = os.path.join(out_dir, "requirements.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        if unique:
            f.write("\n".join(unique) + "\n")
    print(f"\n[✓] Wrote {len(unique)} packages to {out_file}")


def main():
    ap = argparse.ArgumentParser(description="Offline requirements.txt generator")
    ap.add_argument(
        "-v", "--version", type=str, help="Pip command to use (default: pip3)"
    )
    ap.add_argument("-p", "--path", type=str, help="Path to target project directory")
    ap.add_argument(
        "-l",
        "--pypi-list",
        type=str,
        default="/sdcard/data/pip.txt",
        help="Path to offline PyPI package list (default: /sdcard/data/pip.txt)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print result without writing requirements.txt",
    )
    args = vars(ap.parse_args())
    try:
        init(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
