#!/data/data/com.termux/files/home/.local/bin/python
"""
Recursive extractor of classes/functions + top-level constants.
Methods (functions directly inside a class body) are skipped.
Each entity is written to its own file:
 - output/classes/<name>.py
 - output/functions/<name>.py
 - output/const/<name>.py

Usage:
    script.py [file_or_dir ...]
If no input is provided, the current directory is scanned recursively.
"""

import os
import sys
import ast
import multiprocessing as mp

OUTPUT_DIR = "output"
CLASSES_DIR = os.path.join(OUTPUT_DIR, "classes")
FUNCTIONS_DIR = os.path.join(OUTPUT_DIR, "functions")
CONST_DIR = os.path.join(OUTPUT_DIR, "const")
EXCLUDE_DIRS = {"test", "tests", "examples", "output"}
WORKERS = 8


def is_python_script(path: str) -> bool:
    if path.endswith(".py"):
        return True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            line = f.readline()
        return line.startswith("#!") and "python" in line.lower()
    except Exception:
        return False


def collect_files(inputs: list[str]) -> list[str]:
    files: list[str] = []
    for inp in inputs:
        if os.path.isfile(inp):
            if is_python_script(inp):
                files.append(inp)
        elif os.path.isdir(inp):
            for root, dirs, fnames in os.walk(inp):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for fname in fnames:
                    p = os.path.join(root, fname)
                    if is_python_script(p):
                        files.append(p)
    return files


def mark_parents(node: ast.AST, parent=None):
    for child in ast.iter_child_nodes(node):
        setattr(child, "_parent", node)
        mark_parents(child, node)


def is_constant_name(name: str) -> bool:
    return name.isupper()


def extract_from_file(path: str):
    classes: dict[str, str] = {}
    funcs: dict[str, str] = {}
    consts: dict[str, str] = {}

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception:
        return path, classes, funcs, consts

    mark_parents(tree)

    for node in ast.walk(tree):
        parent = getattr(node, "_parent", None)

        if isinstance(node, ast.ClassDef):
            src = ast.get_source_segment(source, node)
            if src:
                classes[node.name] = src

        elif isinstance(node, ast.FunctionDef):
            # Skip methods: functions whose immediate parent is a class body.
            if isinstance(parent, ast.ClassDef):
                continue
            src = ast.get_source_segment(source, node)
            if src:
                funcs[node.name] = src

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Only top-level constants.
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

    return path, classes, funcs, consts


def write_entity(directory: str, name: str, src: str) -> None:
    safe = name.replace(os.sep, "_").replace("/", "_")
    fpath = os.path.join(directory, safe + ".py")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(src.rstrip() + "\n")


def main():
    inputs = sys.argv[1:]
    if not inputs:
        inputs = ["."]

    files = collect_files(inputs)
    if not files:
        print("No Python files found.")
        return

    os.makedirs(CLASSES_DIR, exist_ok=True)
    os.makedirs(FUNCTIONS_DIR, exist_ok=True)
    os.makedirs(CONST_DIR, exist_ok=True)

    all_classes: dict[str, str] = {}
    all_funcs: dict[str, str] = {}
    all_consts: dict[str, str] = {}

    with mp.Pool(WORKERS) as pool:
        for _path, classes, funcs, consts in pool.imap_unordered(
            extract_from_file, files
        ):
            all_classes.update(classes)
            all_funcs.update(funcs)
            all_consts.update(consts)

    for name, src in all_classes.items():
        write_entity(CLASSES_DIR, name, src)
    for name, src in all_funcs.items():
        write_entity(FUNCTIONS_DIR, name, src)
    for name, src in all_consts.items():
        write_entity(CONST_DIR, name, src)

    print(f"Scanned files : {len(files)}")
    print(f"Classes       : {len(all_classes)}")
    print(f"Functions     : {len(all_funcs)}")
    print(f"Constants     : {len(all_consts)}")
    print("Outputs saved to:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
