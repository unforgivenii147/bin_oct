#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import multiprocessing as mp
from ast import AST
from pathlib import Path

OUTPUT_DIR = Path("output")
EXCLUDE_DIRS = {"test", "tests", "examples", "output"}


def is_python_script(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            line = f.readline()
        return line.startswith("#!") and "python" in line.lower()
    except Exception:
        return False


def discover_python_files() -> list[Path]:
    files = []
    base_path = Path(".")
    for path in base_path.rglob("*"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.is_file() and is_python_script(path):
            files.append(path)
    return files


def mark_parents(node: ast.AST, parent: AST | None = None) -> None:
    for child in ast.iter_child_nodes(node):
        child._parent = node
        mark_parents(child, node)


def is_constant_name(name: str) -> bool:
    return name.isupper()


def extract_from_file(
    path: Path,
) -> tuple[
    Path, dict[str, str], dict[str, str], dict[str, str], dict[str, str], dict[str, str]
]:
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return (path, {}, {}, {}, {}, {})
    mark_parents(tree)
    tl_classes, tl_funcs = ({}, {})
    nested_classes, nested_funcs = ({}, {})
    consts = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            src = ast.get_source_segment(source, node)
            if not src:
                continue
            parent = getattr(node, "_parent", None)
            is_toplevel = isinstance(parent, ast.Module)
            if isinstance(node, ast.ClassDef):
                if is_toplevel:
                    tl_classes[node.name] = src
                else:
                    nested_classes[node.name] = src
            elif isinstance(node, ast.FunctionDef):
                if is_toplevel:
                    tl_funcs[node.name] = src
                else:
                    nested_funcs[node.name] = src
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            parent = getattr(node, "_parent", None)
            if not isinstance(parent, ast.Module):
                continue
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
            else:
                continue
            if not is_constant_name(name):
                continue
            src = ast.get_source_segment(source, node)
            if src:
                consts[name] = src
    return (path, tl_classes, tl_funcs, nested_classes, nested_funcs, consts)


def write_output(path: Path, data: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.writelines((src.rstrip() + "\n\n" for _name, src in sorted(data.items())))


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    files = discover_python_files()
    if not files:
        print("No Python files found.")
        return
    with mp.Pool(mp.cpu_count()) as pool:
        results = pool.map(extract_from_file, files)
    tl_classes, tl_funcs = ({}, {})
    nested_classes, nested_funcs = ({}, {})
    const_map = {}
    for _, c, f, nc, nf, consts in results:
        tl_classes.update(c)
        tl_funcs.update(f)
        nested_classes.update(nc)
        nested_funcs.update(nf)
        const_map.update(consts)
    write_output(OUTPUT_DIR / "classes.py", tl_classes)
    write_output(OUTPUT_DIR / "functions.py", tl_funcs)
    write_output(OUTPUT_DIR / "nested_classes.py", nested_classes)
    write_output(OUTPUT_DIR / "nested_functions.py", nested_funcs)
    write_output(OUTPUT_DIR / "const.py", const_map)
    print("\n=== Top-Level Classes ===")
    for n in sorted(tl_classes):
        print(" -", n)
    print("\n=== Top-Level Functions ===")
    for n in sorted(tl_funcs):
        print(" -", n)
    print("\n=== Nested Classes ===")
    for n in sorted(nested_classes):
        print(" -", n)
    print("\n=== Nested Functions ===")
    for n in sorted(nested_funcs):
        print(" -", n)
    print("\n=== Constants ===")
    for n in sorted(const_map):
        print(" -", n)
    print("\nOutputs saved to:", OUTPUT_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
