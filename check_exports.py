#!/data/data/com.termux/files/home/.local/bin/python
"""
Check Python files in current directory and report definitions
that are not exported in __init__.py.

Usage:
    python check_exports.py           # just report
    python check_exports.py -a        # autofix __init__.py
    python check_exports.py -a --dry-run  # preview autofix changes
"""

import argparse
import ast
from pathlib import Path
from typing import Dict

from loguru import logger


def extract_definitions(path: Path) -> dict[str, list[str]]:
    """
    Extract top-level definitions from a Python file.

    Returns:
        Dict with keys 'functions', 'classes', 'constants' and lists of names
    """
    definitions = {"functions": [], "classes": [], "constants": []}

    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse {path}: {e}")
        return definitions
    except Exception as e:
        logger.error(f"Unexpected error reading {path}: {e}")
        return definitions

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                definitions["functions"].append(node.name)

        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                definitions["classes"].append(node.name)

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.isupper() and not name.startswith("_"):
                        definitions["constants"].append(name)

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.isupper() and not name.startswith("_"):
                definitions["constants"].append(name)

    return definitions


def extract_exports_from_init(init_path: Path) -> set[str]:
    """
    Extract names exported from __init__.py.
    Handles both __all__ and direct imports.
    """
    exported = set()

    try:
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=str(init_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse {init_path}: {e}")
        return exported
    except Exception as e:
        logger.error(f"Unexpected error reading {init_path}: {e}")
        return exported

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(
                                elt.value, str
                            ):
                                exported.add(elt.value)

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    logger.warning(f"Wildcard import found in {init_path}")
                    continue
                exported.add(alias.asname or alias.name)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                exported.add(name)

    return exported


def check_directory(directory: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """
    Check all Python files in directory against __init__.py exports.

    Returns:
        Dict mapping filename -> {'functions': [...], 'classes': [...], 'constants': [...]}
        containing names that are defined but NOT exported.
    """
    if directory is None:
        directory = Path.cwd()

    init_path = directory / "__init__.py"

    if not init_path.exists():
        logger.error(f"No __init__.py found in {directory}")
        return {}

    print(f"Reading exports from {init_path}")
    exported = extract_exports_from_init(init_path)
    logger.debug(f"Found {len(exported)} exported names: {sorted(exported)}")

    missing = {}

    python_files = [
        f
        for f in directory.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    ]

    if not python_files:
        logger.warning(f"No Python module files found in {directory}")
        return {}

    for py_file in sorted(python_files):
        logger.debug(f"Scanning {py_file.name}")
        definitions = extract_definitions(py_file)

        module_name = py_file.stem
        file_missing = {"functions": [], "classes": [], "constants": []}

        for category, names in definitions.items():
            for name in names:
                if name not in exported and module_name not in exported:
                    file_missing[category].append(name)

        if any(file_missing.values()):
            missing[py_file.name] = file_missing

    return missing


def build_import_block(missing: dict[str, dict[str, list[str]]]) -> str:
    """
    Build import statements + __all__ block for missing definitions.

    Groups imports by module and produces something like:
        from .foo import (bar, Baz)
        from .bar import QUX

        __all__ = [
            "bar",
            "Baz",
            "QUX",
        ]
    """
    import_lines = []
    all_names = []

    for filename in sorted(missing.keys()):
        module_name = Path(filename).stem
        categories = missing[filename]

        # Collect all names for this module, sorted alphabetically
        names = sorted(
            categories["classes"] + categories["constants"] + categories["functions"]
        )
        if not names:
            continue

        if len(names) == 1:
            import_lines.append(f"from .{module_name} import {names[0]}")
        else:
            names_str = ", ".join(names)
            import_lines.append(f"from .{module_name} import ({names_str})")

        all_names.extend(names)

    all_names.sort()
    all_block_lines = ["", "__all__ = ["]
    for name in all_names:
        all_block_lines.append(f'    "{name}",')
    all_block_lines.append("]")

    return "\n".join(import_lines) + "\n" + "\n".join(all_block_lines) + "\n"


def autofix_init(
    init_path: Path, missing: dict[str, dict[str, list[str]]], dry_run: bool = False
) -> bool:
    """
    Append missing imports and __all__ entries to __init__.py.

    Strategy:
    - If __init__.py already has an __all__, insert new entries into it
      (and append imports at the end).
    - If no __all__ exists, append imports + a new __all__ at the end.

    Returns True on success.
    """
    if not missing:
        return True

    try:
        original = init_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read {init_path}: {e}")
        return False

    try:
        tree = ast.parse(original, filename=str(init_path))
    except SyntaxError as e:
        logger.error(f"Cannot autofix, {init_path} has a syntax error: {e}")
        return False

    # Detect existing __all__ assignment
    all_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    all_node = node
                    break
        if all_node:
            break

    # Gather names that need to be added
    new_names = sorted(
        {
            name
            for categories in missing.values()
            for names in categories.values()
            for name in names
        }
    )

    # Build import lines
    import_lines = []
    for filename in sorted(missing.keys()):
        module_name = Path(filename).stem
        categories = missing[filename]
        names = sorted(
            categories["classes"] + categories["constants"] + categories["functions"]
        )
        if not names:
            continue
        if len(names) == 1:
            import_lines.append(f"from .{module_name} import {names[0]}")
        else:
            names_str = ", ".join(names)
            import_lines.append(f"from .{module_name} import ({names_str})")

    if all_node is not None:
        # Insert new names into existing __all__ (as strings, sorted)
        existing_names = set()
        if isinstance(all_node.value, (ast.List, ast.Tuple)):
            for elt in all_node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    existing_names.add(elt.value)

        combined = sorted(existing_names | set(new_names))

        # Rebuild the __all__ block
        new_all_block = "__all__ = [\n"
        for name in combined:
            new_all_block += f'    "{name}",\n'
        new_all_block += "]"

        # Replace via line splicing
        lines = original.splitlines(keepends=True)
        start = all_node.lineno - 1
        end = all_node.end_lineno  # exclusive end line index (0-based)

        # Preserve indentation if inside something (unlikely for __all__)
        new_lines = lines[:start] + [new_all_block + "\n"] + lines[end:]
        updated = "".join(new_lines)

        # Append new imports at end
        if import_lines:
            if not updated.endswith("\n"):
                updated += "\n"
            updated += "\n" + "\n".join(import_lines) + "\n"
    else:
        # No __all__: append imports + new __all__ block
        updated = original
        if not updated.endswith("\n"):
            updated += "\n"
        updated += "\n"
        updated += "\n".join(import_lines) + "\n"
        updated += "\n__all__ = [\n"
        for name in new_names:
            updated += f'    "{name}",\n'
        updated += "]\n"

    if dry_run:
        print("\n" + "=" * 70)
        print(f"DRY RUN — would write to {init_path}:")
        print("=" * 70)
        # Show only the diff-like addition
        print("--- Proposed additions ---")
        print("\n".join(import_lines))
        print()
        print("__all__ entries added:", new_names)
        return True

    try:
        init_path.write_text(updated, encoding="utf-8")
        logger.success(f"Updated {init_path} with {len(new_names)} new export(s)")
        return True
    except Exception as e:
        logger.error(f"Failed to write {init_path}: {e}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check and optionally autofix __init__.py exports."
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically add missing definitions to __init__.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With -a, show what would be changed without writing",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="<level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if args.verbose else "INFO",
        colorize=True,
    )

    directory = args.directory.resolve()
    print(f"Checking package definitions in: {directory}")

    missing = check_directory(directory)

    if not missing:
        logger.success("All definitions are exported in __init__.py")
        return 0

    print()
    print("=" * 70)
    print("DEFINITIONS NOT EXPORTED IN __init__.py")
    print("=" * 70)

    total = 0
    for filename, categories in missing.items():
        print(f"\n📄 {filename}")
        for category, names in categories.items():
            if names:
                total += len(names)
                icon = {"functions": "🔧", "classes": "🏛️ ", "constants": "📌"}[category]
                print(f"  {icon} {category.capitalize()}:")
                for name in sorted(names):
                    print(f"      - {name}")

    print()
    print("=" * 70)
    logger.warning(f"Total missing definitions: {total}")

    if args.autofix:
        print()
        if args.dry_run:
            print("Dry-run mode enabled — no files will be modified")
        else:
            print("Autofix enabled — updating __init__.py")

        init_path = directory / "__init__.py"
        success = autofix_init(init_path, missing, dry_run=args.dry_run)
        return 0 if success else 1
    else:
        print()
        print("Run with -a to automatically add these to __init__.py")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
