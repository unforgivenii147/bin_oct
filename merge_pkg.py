#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import base64
import json
import os
import sys
from pathlib import Path


class Module:
    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        self.imports = []
        self.functions = []
        self.classes = []
        self.assignments = []
        self.main_body = []
        self.dunder_all = None


def parse_module(module: Module):
    source = module.path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            module.dunder_all = node
            module.assignments.append(node)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module.imports.append(node)
            continue
        if isinstance(node, ast.If):
            test = ast.unparse(node.test)
            if "__name__" in test and "__main__" in test:
                module.main_body.extend(node.body)
                continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.append(node)
        elif isinstance(node, ast.ClassDef):
            module.classes.append(node)
        else:
            module.assignments.append(node)


def resolve_imports(modules: dict, root_pkg_name: str) -> list:
    final_imports = []
    for mod in modules.values():
        for imp in mod.imports:
            if isinstance(imp, ast.ImportFrom) and imp.level > 0:
                parts = mod.name.split(".")
                if imp.level > 1:
                    base_parts = parts[: -(imp.level - 1)]
                else:
                    base_parts = parts[:-1]
                base_pkg = ".".join(base_parts)
                if imp.module:
                    abs_module = f"{base_pkg}.{imp.module}" if base_pkg else imp.module
                else:
                    abs_module = base_pkg
                imp.module = abs_module
                imp.level = 0
                if abs_module == root_pkg_name and not imp.names[0].name == "*":
                    new_imports = []
                    for alias in imp.names:
                        new_imports.append(
                            ast.parse(
                                f"import {root_pkg_name}.{alias.name} as {alias.asname or alias.name}"
                            ).body[0]
                        )
                    final_imports.extend(new_imports)
                    continue
            final_imports.append(imp)
        mod.imports = []
    return final_imports


def package_assets(asset_dir: Path, root_pkg_name: str) -> tuple:
    assets = {}
    for root, _, files in os.walk(asset_dir):
        for f in files:
            fp = Path(root) / f
            rel_path = fp.relative_to(asset_dir.parent)
            assets[str(rel_path)] = base64.b64encode(fp.read_bytes()).decode("utf-8")
    assets_json = json.dumps(assets, indent=4)
    loader_code = f"""
import os, base64, tempfile
_ASSETS = {assets_json}
_TEMP_DIR = tempfile.mkdtemp()
for _rel_path, _b64 in _ASSETS.items():
    _abs_path = os.path.join(_TEMP_DIR, _rel_path)
    os.makedirs(os.path.dirname(_abs_path), exist_ok=True)
    with open(_abs_path, 'wb') as _f:
        _f.write(base64.b64decode(_b64))
_orig_open = open
def _patched_open(file, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    _str_file = str(file)
    if isinstance(file, str) and (_str_file.startswith("{root_pkg_name}/") or _str_file.startswith("{root_pkg_name}\\\\")):
        _new_path = os.path.join(_TEMP_DIR, _str_file)
        return _orig_open(_new_path, mode, buffering, encoding, errors, newline, closefd, opener)
    return _orig_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
import builtins
builtins.open = _patched_open
"""
    return ast.parse(loader_code).body


def merge_package(project_dir: str, output_file: str):
    project_path = Path(project_dir).resolve()
    root_pkg_name = project_path.name
    py_files = list(project_path.rglob("*.py"))
    asset_dir = project_path / "assets"
    modules = {}
    for py_file in py_files:
        if py_file.name == "__pycache__":
            continue
        rel_path = py_file.relative_to(project_path.parent)
        mod_name = ".".join(rel_path.with_suffix("").parts)
        mod_name = mod_name.removesuffix(".__init__")
        mod = Module(mod_name, py_file)
        parse_module(mod)
        modules[mod_name] = mod
    all_imports = resolve_imports(modules, root_pkg_name)
    asset_nodes = []
    if asset_dir.exists():
        asset_nodes = package_assets(asset_dir, root_pkg_name)
    final_body = []
    final_body.extend(asset_nodes)
    final_body.extend(all_imports)
    for mod in modules.values():
        final_body.extend(mod.assignments)
    for mod in modules.values():
        final_body.extend(mod.classes)
    for mod in modules.values():
        final_body.extend(mod.functions)
    for mod in modules.values():
        if mod.main_body:
            final_body.append(ast.parse("if __name__ == '__main__':").body[0])
            final_body[-1].body = mod.main_body
    header = f'"""Single-file build of {root_pkg_name}"""\n'
    final_code = header + ast.unparse(ast.Module(body=final_body, type_ignores=[]))
    Path(output_file).write_text(final_code, encoding="utf-8")
    print(f"Successfully merged {root_pkg_name} into {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python merge_package.py <project_dir> <output_file>")
        sys.exit(1)
    merge_package(sys.argv[1], sys.argv[2])
