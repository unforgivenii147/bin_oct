#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path

import tree_sitter_python as tsp
from dh import get_pyfiles
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tsp.language())
parser = Parser(PY_LANGUAGE)


def extract_python_code_elements(path: Path):
    try:
        with Path(path).open("rb") as f:
            tree = parser.parse(f.read())
    except Exception as e:
        print(f"Error parsing file {path}: {e}")
        return [], [], []
    functions = []
    classes = []
    constants = []
    imports = []
    nodes_to_visit = [tree.root_node]
    while nodes_to_visit:
        node = nodes_to_visit.pop(0)
        for child in node.children:
            if child.type == "function_definition":
                func_name_node = child.child_by_field_name("name")
                if func_name_node:
                    functions.append(func_name_node.text.decode("utf-8"))
            elif child.type == "class_definition":
                class_name_node = child.child_by_field_name("name")
                if class_name_node:
                    classes.append(class_name_node.text.decode("utf-8"))
            elif child.type == "assignment" and node.type not in {
                "import_statement",
                "import_from_statement",
            }:
                target = child.child_by_field_name("name")
                if (
                    target
                    and target.text.decode("utf-8").isupper()
                    and len(target.text.decode("utf-8")) > 1
                ) and child.named_child_count == 2:
                    constants.append(target.text.decode("utf-8"))
            elif child.type == "import_statement":
                imports.extend(
                    import_node.text.decode("utf-8")
                    for import_node in child.children
                    if import_node.type == "dotted_name"
                )
            elif child.type == "import_from_statement":
                module_name_node = child.child_by_field_name("module_name")
                if module_name_node:
                    module_name = module_name_node.text.decode("utf-8")
                    for import_spec_node in child.children:
                        if import_spec_node.type == "import_spec":
                            for name_node in import_spec_node.children:
                                if name_node.type == "dotted_name":
                                    imports.append(
                                        f"{module_name}.{name_node.text.decode('utf-8')}"
                                    )
                                elif name_node.type == "aliased_import":
                                    aliased_name_node = name_node.child_by_field_name(
                                        "name"
                                    )
                                    if aliased_name_node:
                                        imports.append(
                                            f"{module_name}.{aliased_name_node.text.decode('utf-8')}"
                                        )
            if child.children:
                nodes_to_visit.append(child)
    return functions, classes, constants, imports


def process_directory(start_dir: str, output_dir: str) -> None:
    all_functions = {}
    all_classes = {}
    all_constants = {}
    all_imports = set()
    if not Path(output_dir).exists():
        Path(output_dir).mkdir(parents=True)
        print(f"Created output directory: {output_dir}")
    imports_output_path = os.path.join(output_dir, "imports.py")
    for path in get_pyfiles(start_dir):
        functions, classes, constants, imports = extract_python_code_elements(path)
        if functions:
            all_functions["relative_path"] = functions
        if classes:
            all_classes["relative_path"] = classes
        if constants:
            all_constants["relative_path"] = constants
        all_imports.update(imports)
    with Path(os.path.join(output_dir, "functions.txt")).open(
        "w", encoding="utf-8"
    ) as f:
        for file, funcs in all_functions.items():
            f.write(f"# File: {file}\n")
            f.writelines(f"{func}\n" for func in funcs)
            f.write("\n")
    with Path(os.path.join(output_dir, "classes.txt")).open("w", encoding="utf-8") as f:
        for file, cls in all_classes.items():
            f.write(f"# File: {file}\n")
            f.writelines(f"{c}\n" for c in cls)
            f.write("\n")
    with Path(os.path.join(output_dir, "constants.txt")).open(
        "w", encoding="utf-8"
    ) as f:
        for file, consts in all_constants.items():
            f.write(f"# File: {file}\n")
            f.writelines(f"{const}\n" for const in consts)
            f.write("\n")
    with Path(imports_output_path).open("w", encoding="utf-8") as f:
        if all_imports:
            f.write("# Extracted Imports\n\n")
            f.writelines(f"import {imp}\n" for imp in sorted(all_imports))
        else:
            f.write("# No imports found.\n")
    print(f"\nExtraction complete. Results saved to '{output_dir}'.")
    print(f"Imports saved to '{imports_output_path}'.")


if __name__ == "__main__":
    cwdectory = "."
    output_directory = "output"
    if not Path(output_directory).exists():
        Path(output_directory).mkdir(parents=True)
    print("Starting code element extraction...")
    process_directory(cwdectory, output_directory)
