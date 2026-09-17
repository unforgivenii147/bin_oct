#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path


def extract_imports(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
    except Exception as e:
        print(f"  ✗ Error parsing {path}: {e}")
        return set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                imports.add(module_name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module_name = node.module.split(".")[0]
            imports.add(module_name)
    return imports


def is_stdlib(module_name):
    if hasattr(sys, "stdlib_module_names"):
        return module_name in sys.stdlib_module_names
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return False
        if spec.origin is None:
            return True
        origin = Path(spec.origin)
        return "site-packages" not in str(origin)
    except (ImportError, ValueError, AttributeError):
        return False


def get_local_modules(cwd="."):
    root = Path(cwd)
    local_modules = set()
    for py_file in root.glob("**/*.py"):
        module_name = py_file.stem
        local_modules.add(module_name)
    return local_modules


def collect_requirements(cwd: str = ".", exclude_dirs=None, verbose=False):
    if exclude_dirs is None:
        exclude_dirs = {
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            ".pytest_cache",
            "env",
            ".env",
            "node_modules",
            ".idea",
            "build",
            "dist",
        }
    root = Path(cwd)
    all_imports = set()
    local_modules = get_local_modules(cwd)
    import_sources = defaultdict(list)
    print(f"Scanning {root}...\n")
    for py_file in sorted(root.glob("**/*.py")):
        if any(part in exclude_dirs for part in py_file.parts):
            continue
        imports = extract_imports(py_file)
        if imports:
            if verbose:
                print(f"  {py_file}: {imports}")
            for imp in imports:
                import_sources[imp].append(str(py_file))
            all_imports.update(imports)
    print(f"\nFound {len(all_imports)} unique imports")
    print(f"Local modules: {local_modules}\n")
    third_party = []
    skipped_stdlib = []
    skipped_local = []
    for module in sorted(all_imports):
        if module == "__main__":
            continue
        if module in local_modules:
            skipped_local.append(module)
            continue
        if is_stdlib(module):
            skipped_stdlib.append(module)
            continue
        third_party.append(module)
    if verbose:
        if skipped_stdlib:
            print(f"Skipped stdlib ({len(skipped_stdlib)}): {skipped_stdlib}")
        if skipped_local:
            print(f"Skipped local ({len(skipped_local)}): {skipped_local}")
    return third_party


def write_requirements(packages, output_file: str = "requirements.txt") -> Path:
    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(f"{package}\n" for package in packages)
    print(f"\n✓ Written {len(packages)} packages to {output_path}\n")
    if packages:
        print("Contents of requirements.txt:")
        print("-" * 40)
        for pkg in packages:
            print(f"  {pkg}")
        print("-" * 40)
    else:
        print("(No third-party packages found)")
    return output_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate requirements.txt by scanning Python files"
    )
    parser.add_argument(
        "-d",
        "--dir",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="requirements.txt",
        help="Output file (default: requirements.txt)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug info")
    args = parser.parse_args()
    packages = collect_requirements(args.dir, verbose=args.verbose)
    write_requirements(packages, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
