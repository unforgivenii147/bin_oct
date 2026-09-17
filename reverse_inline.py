#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def get_function_source_hash(source: str, func_name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = source.split("\n")
            func_lines = lines[node.lineno - 1 : node.end_lineno]
            func_source = "\n".join(func_lines)
            return hashlib.sha256(func_source.encode()).hexdigest()
    return None


def extract_functions_from_module(module_path: Path) -> dict[str, tuple[str, str]]:
    if not module_path.is_file():
        return {}
    try:
        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()
            tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return {}
    functions = {}
    module_name = module_path.stem
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_hash = get_function_source_hash(source, node.name)
            if func_hash:
                functions[node.name] = (module_name, func_hash)
    return functions


def build_dh_function_map(dh_src_path: Path) -> dict[str, tuple[str, str]]:
    func_map = {}
    for module_file in dh_src_path.glob("*.py"):
        if module_file.name == "__init__.py":
            continue
        functions = extract_functions_from_module(module_file)
        func_map.update(functions)
    return func_map


def find_matching_inlined_functions(
    source: str, dh_func_map: dict[str, tuple[str, str]]
) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in dh_func_map:
            func_hash = get_function_source_hash(source, node.name)
            _dh_module_name, dh_hash = dh_func_map[node.name]
            if func_hash and func_hash == dh_hash:
                matches.append((node.name, node.lineno - 1, node.end_lineno))
    return matches


def has_import(source: str, func_name: str) -> bool:
    return (
        f"from dh.{func_name} import" in source
        or f"from dh import {func_name}" in source
        or ("from dh import" in source and f"{func_name}" in source)
    )


def add_imports(lines: list[str], imports: set[tuple[str, str]]) -> list[str]:
    if not imports:
        return lines
    last_import_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            last_import_idx = i
    import_lines = sorted(
        [f"from dh.{module} import {func}" for func, module in imports]
    )
    if last_import_idx == -1:
        return import_lines + [""] + lines
    else:
        return (
            lines[: last_import_idx + 1] + import_lines + lines[last_import_idx + 1 :]
        )


def process_file(
    path: Path, dh_func_map: dict[str, tuple[str, str]], dry_run: bool = True
) -> tuple[Path, int, set[tuple[str, str]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return (path, 0, set())
    matches = find_matching_inlined_functions(content, dh_func_map)
    if not matches:
        return (path, 0, set())
    lines = content.split("\n")
    imports_needed = set()
    for func_name, start_line, end_line in matches:
        if not has_import(content, func_name):
            module_name, _ = dh_func_map[func_name]
            imports_needed.add((func_name, module_name))
    if not imports_needed:
        return (path, 0, set())
    if not dry_run:
        matches_sorted = sorted(matches, key=lambda x: x[1], reverse=True)
        for func_name, start_line, end_line in matches_sorted:
            del lines[start_line:end_line]
        lines = add_imports(lines, imports_needed)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return (path, len(imports_needed), imports_needed)


def main():
    parser = argparse.ArgumentParser(
        description="Reverse inline functions from dh package"
    )
    parser.add_argument(
        "-n",
        "--no-dry-run",
        action="store_true",
        help="Actually modify files (dry-run by default)",
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to process")
    args = parser.parse_args()
    dry_run = not args.no_dry_run
    dh_path = Path.home() / "projects" / "py" / "dh" / "src" / "dh"
    bin_path = Path.cwd()
    target_paths = (
        [Path(p).expanduser() for p in args.paths] if args.paths else [bin_path]
    )
    if not dh_path.is_dir():
        print(f"Error: dh package not found at {dh_path}")
        sys.exit(1)
    print(f"Building function map from {dh_path}...")
    dh_func_map = build_dh_function_map(dh_path)
    print(f"Found {len(dh_func_map)} functions in dh package\n")
    py_files = []
    for target_path in target_paths:
        if target_path.is_file() and target_path.suffix == ".py":
            py_files.append(target_path)
        elif target_path.is_dir():
            py_files.extend(target_path.rglob("*.py"))
    mode = "DRY RUN" if dry_run else "ACTUAL"
    print(f"{mode} MODE: Processing {len(py_files)} Python files...\n")
    with ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(process_file, py_file, dh_func_map, dry_run): py_file
            for py_file in py_files
        }
        total_removed = 0
        changes_by_file = {}
        for future in as_completed(futures):
            path, count, imports = future.result()
            if count > 0:
                changes_by_file[path] = imports
                total_removed += count
    if not changes_by_file:
        print("No matching inlined dh functions found (identical by content hash).")
        return
    for path in sorted(changes_by_file.keys()):
        imports = changes_by_file[path]
        print(f"{path.name}:")
        for func_name, module_name in sorted(imports):
            print(
                f"  - Replace {func_name}() and add: from dh.{module_name} import {func_name}"
            )
        print()
    print(f"Total functions to process: {total_removed}")
    if dry_run:
        print("\n✓ DRY RUN complete. Run with -n/--no-dry-run to apply changes.")
    else:
        print("\n✓ Changes applied successfully.")


if __name__ == "__main__":
    raise SystemExit(main())
