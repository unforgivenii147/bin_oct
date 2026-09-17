#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import os
from ast import AST
from pathlib import Path

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)
func_file = output_dir / "func.py"
classes_file = output_dir / "classes.py"
const_file = output_dir / "const.py"
init_file = output_dir / "__init__.py"
for file in [func_file, classes_file, const_file, init_file]:
    if file.exists():
        file.unlink()


def is_constant(node: AST) -> bool:
    return isinstance(node, ast.Assign) and all(
        isinstance(t, ast.Name) for t in node.targets
    )


def write_to_file(path: Path, content) -> None:
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(content + "\n\n")


for root, _, files in os.walk("."):
    for file in files:
        if file.endswith(".py") and not file.startswith("output"):
            path = Path(root) / file
            content = Path(path).read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_code = ast.get_source(tree, node)
                    write_to_file(func_file, func_code)
                elif isinstance(node, ast.ClassDef):
                    class_code = ast.get_source(tree, node)
                    write_to_file(classes_file, class_code)
                elif is_constant(node):
                    const_code = ast.get_source(tree, node)
                    write_to_file(const_file, const_code)
with Path(init_file).open("w", encoding="utf-8") as f:
    f.write("from .func import *\n")
    f.write("from .classes import *\n")
    f.write("from .const import *\n")
func_content = func_file.read_text() if func_file.exists() else ""
classes_content = classes_file.read_text() if classes_file.exists() else ""
const_content = const_file.read_text() if const_file.exists() else ""
init_content = init_file.read_text() if init_file.exists() else ""
func_content, classes_content, const_content, init_content
