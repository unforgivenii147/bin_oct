#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import os
from ast import Module
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from pathlib import Path


def parse_python_file(path) -> Module:
    with open(path, encoding="utf-8") as file:
        return ast.parse(file.read(), filename=path)


def extract_definitions(tree: Module):
    functions = []
    classes = []
    constants = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.append(target.id)
    return functions, classes, constants


def find_repeated_definitions(paths):
    definition_counts = defaultdict(lambda: defaultdict(int))
    for path in paths:
        tree = parse_python_file(path)
        functions, classes, constants = extract_definitions(tree)
        for func in functions:
            definition_counts["functions"][func] += 1
        for cls in classes:
            definition_counts["classes"][cls] += 1
        for const in constants:
            definition_counts["constants"][const] += 1
    repeated_definitions = {
        "functions": [
            name for name, count in definition_counts["functions"].items() if count > 1
        ],
        "classes": [
            name for name, count in definition_counts["classes"].items() if count > 1
        ],
        "constants": [
            name for name, count in definition_counts["constants"].items() if count > 1
        ],
    }
    return repeated_definitions


def process_file(path, repeated_definitions, move) -> None:
    path = Path(path)
    tree = parse_python_file(path)
    _functions, _classes, _constants = extract_definitions(tree)
    utils_dir = "utils"
    os.makedirs(utils_dir, exist_ok=True)

    def write_to_file(filename: str, content: str) -> None:
        with open(os.path.join(utils_dir, filename), "a", encoding="utf-8") as f:
            f.write(content + "\n")

    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    new_lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in repeated_definitions["functions"]
        ):
            func_code = "".join(lines[node.lineno - 1 : node.end_lineno])
            write_to_file("func.py", func_code)
            if move:
                continue
        elif (
            isinstance(node, ast.ClassDef)
            and node.name in repeated_definitions["classes"]
        ):
            class_code = "".join(lines[node.lineno - 1 : node.end_lineno])
            write_to_file("class.py", class_code)
            if move:
                continue
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in repeated_definitions["constants"]
                ):
                    const_code = "".join(lines[node.lineno - 1 : node.end_lineno])
                    write_to_file("const.py", const_code)
                    if move:
                        break
            else:
                new_lines.append(lines[node.lineno - 1])
                continue
        new_lines.append(lines[node.lineno - 1])
    if move:
        with open(path, "w", encoding="utf-8") as file:
            file.writelines(new_lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Python files and copy/move repeated definitions."
    )
    parser.add_argument(
        "-m", "--move", action="store_true", help="Move definitions instead of copying"
    )
    args = parser.parse_args()
    python_files = []
    for root, _, files in os.walk("."):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    repeated_definitions = find_repeated_definitions(python_files)
    with Pool(cpu_count()) as pool:
        pool.starmap(
            process_file,
            [(path, repeated_definitions, args.move) for path in python_files],
        )


if __name__ == "__main__":
    raise SystemExit(main())
