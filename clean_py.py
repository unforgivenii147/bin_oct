#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import multiprocessing as mp
import shutil
import traceback
from pathlib import Path


class UsageAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.func_defs = set()
        self.class_defs = set()
        self.var_defs = set()
        self.var_uses = set()
        self.func_calls = set()
        self.class_uses = set()
        self.imports = {}
        self.import_uses = set()

    def visit_FunctionDef(self, node) -> None:
        self.func_defs.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node) -> None:
        self.class_defs.add(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node) -> None:
        if isinstance(node.parent, ast.Module):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.var_defs.add(target.id)
        self.generic_visit(node)

    def visit_Name(self, node) -> None:
        if isinstance(node.ctx, ast.Load):
            self.var_uses.add(node.id)
            self.func_calls.add(node.id)
            self.class_uses.add(node.id)
            self.import_uses.add(node.id)
        self.generic_visit(node)

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name] = node

    def visit_ImportFrom(self, node) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name] = node


def annotate_parents(tree) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


def find_unused_symbols(source: str):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}, ["SyntaxError while parsing file"]
    annotate_parents(tree)
    analyzer = UsageAnalyzer()
    analyzer.visit(tree)
    unused = {}
    unused_funcs = analyzer.func_defs - analyzer.func_calls
    unused_classes = analyzer.class_defs - analyzer.class_uses
    unused_vars = analyzer.var_defs - analyzer.var_uses
    unused_imports = {
        name: node
        for name, node in analyzer.imports.items()
        if name not in analyzer.import_uses
    }
    unused["functions"] = sorted(unused_funcs)
    unused["classes"] = sorted(unused_classes)
    unused["variables"] = sorted(unused_vars)
    unused["imports"] = unused_imports
    return unused, []


def remove_unused(source: str, unused) -> str:
    tree = ast.parse(source)
    annotate_parents(tree)
    new_body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in unused["functions"]:
            continue
        if isinstance(node, ast.ClassDef) and node.name in unused["classes"]:
            continue
        if isinstance(node, ast.Assign) and isinstance(node.parent, ast.Module):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if all(t in unused["variables"] for t in targets):
                continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(alias.asname or alias.name) for alias in node.names]
            if all(n in unused["imports"] for n in names):
                continue
        new_body.append(node)
    tree.body = new_body
    return ast.unparse(tree)


def process_file(path, dry_run: bool = False):
    Path(path)
    errors = []
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        return path, {}, [f"Error reading file: {e}"]
    unused, parse_errors = find_unused_symbols(source)
    errors.extend(parse_errors)
    nothing_to_remove = (
        not unused["functions"]
        and not unused["classes"]
        and not unused["variables"]
        and not unused["imports"]
    )
    if nothing_to_remove:
        return path, unused, errors
    try:
        new_source = remove_unused(source, unused)
    except Exception:
        errors.append("Error rewriting file:\n" + traceback.format_exc())
        return path, unused, errors
    if not dry_run:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)
        path.write_text(new_source, encoding="utf-8")
    return path, unused, errors


def gather_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def worker(args):
    return process_file(*args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove unused functions, classes, variables, and imports."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files.",
    )
    parser.add_argument(
        "--workers", type=int, default=mp.cpu_count(), help="Number of processes"
    )
    args = parser.parse_args()
    root = Path.cwd()
    py_files = gather_python_files(root)
    print(f"Scanning {len(py_files)} Python files...")
    with mp.Pool(args.workers) as pool:
        results = pool.map(worker, [(f, args.dry_run) for f in py_files])
    print("\n=== RESULTS ===\n")
    for path, unused, errors in results:
        if any(unused.values()):
            if args.dry_run:
                print(f"[DRY-RUN] {path}")
            else:
                print(f"Updated {path} (backup created)")
            if unused["functions"]:
                print("  Unused functions:", unused["functions"])
            if unused["classes"]:
                print("  Unused classes:", unused["classes"])
            if unused["variables"]:
                print("  Unused variables:", unused["variables"])
            if unused["imports"]:
                print("  Unused imports:", list(unused["imports"].keys()))
        for err in errors:
            print(f"[ERROR] {path}: {err}")


if __name__ == "__main__":
    raise SystemExit(main())
