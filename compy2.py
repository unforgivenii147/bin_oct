#!/data/data/com.termux/files/home/.local/bin/python
import ast
import builtins
import string
import sys
from pathlib import Path
from dh import cprint


PROTECTED_NAMES = set(dir(builtins)) | {
    "__file__",
    "__name__",
    "__doc__",
    "__main__",
    "self",
    "cls",
}


# ---------- stdlib discovery ----------
def get_stdlib_modules():
    """Return the set of top-level stdlib module names."""
    if hasattr(sys, "stdlib_module_names"):  # Python 3.10+
        return set(sys.stdlib_module_names)

    # Fallback for older Pythons
    import sysconfig

    stdlib_path = Path(sysconfig.get_paths()["stdlib"])
    mods = set(sys.builtin_module_names)
    for entry in stdlib_path.iterdir():
        name = entry.name
        if name.endswith(".py"):
            mods.add(name[:-3])
        elif name.endswith(".so"):
            mods.add(name.split(".")[0])
        elif entry.is_dir():
            mods.add(name)
    return mods


STDLIB_MODULES = get_stdlib_modules()
STDLIB_KEEP = {"__future__"}  # never strip __future__


# ---------- docstring / type stripping ----------
class StripDocstringsAndTypes(ast.NodeTransformer):
    """Removes docstrings, return types, parameter annotations, and AnnAssign targets."""

    def visit_FunctionDef(self, node):
        node.returns = None
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.returns = None
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        # `x: int = 1` -> `x = 1`  |  `x: int` -> dropped
        if node.value is None:
            return None
        new_node = ast.Assign(targets=[node.target], value=node.value)
        return self.generic_visit(new_node)

    def _remove_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)


# ---------- stdlib import stripper ----------
class StdlibImportStripper(ast.NodeTransformer):
    """Removes imports that reference stdlib modules; records them for the trailing notice."""

    def __init__(self):
        self.removed = []

    def visit_Import(self, node):
        kept = []
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in STDLIB_MODULES and top not in STDLIB_KEEP:
                text = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                self.removed.append(text)
            else:
                kept.append(alias)
        if not kept:
            return None
        node.names = kept
        return node

    def visit_ImportFrom(self, node):
        if node.module is None:
            return node
        top = node.module.split(".")[0]
        if top in STDLIB_KEEP:
            return node
        if top in STDLIB_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    self.removed.append(f"from {node.module} import *")
                elif alias.asname:
                    self.removed.append(
                        f"from {node.module} import {alias.name} as {alias.asname}"
                    )
                else:
                    self.removed.append(f"from {node.module} import {alias.name}")
            return None
        return node


# ---------- name generation / collection / renaming ----------
def generate_short_names():
    letters = string.ascii_lowercase
    idx = 0
    while True:
        if idx < 26:
            yield letters[idx]
        else:
            yield f"{letters[idx % 26]}{idx // 26}"
        idx += 1


class NameCollector(ast.NodeVisitor):
    def __init__(self, name_map, name_gen):
        self.name_map = name_map
        self.name_gen = name_gen

    def _register(self, name):
        if (
            name
            and len(name) > 3
            and name not in PROTECTED_NAMES
            and not name.startswith("__")
            and name not in self.name_map
        ):
            self.name_map[name] = next(self.name_gen)

    def visit_FunctionDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_arg(self, node):
        self._register(node.arg)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self._register(node.id)


class NameRenamer(ast.NodeTransformer):
    def __init__(self, name_map):
        self.name_map = name_map

    def _map(self, name):
        return self.name_map.get(name, name)

    def visit_FunctionDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.arg = self._map(node.arg)
        return node

    def visit_Name(self, node):
        node.id = self._map(node.id)
        return node


# ---------- driver ----------
def compress_files(file_paths):
    name_map = {}
    name_gen = generate_short_names()
    parsed_trees = []
    removed_imports = []

    # First pass: parse, strip types/docstrings, collect names, strip stdlib imports
    for filepath in file_paths:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: File '{filepath}' not found. Skipping.", file=sys.stderr)
            continue

        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=filepath)

        tree = StripDocstringsAndTypes().visit(tree)
        ast.fix_missing_locations(tree)

        NameCollector(name_map, name_gen).visit(tree)

        stripper = StdlibImportStripper()
        tree = stripper.visit(tree)
        ast.fix_missing_locations(tree)
        removed_imports.extend(stripper.removed)

        parsed_trees.append((filepath, tree))

    # Second pass: rename + unparse
    output_parts = []
    for filepath, tree in parsed_trees:
        tree = NameRenamer(name_map).visit(tree)
        ast.fix_missing_locations(tree)

        minified = ast.unparse(tree)
        cleaned_lines = [ln for ln in minified.splitlines() if ln.strip()]
        output_parts.append(f"# --- File: {filepath} ---\n" + "\n".join(cleaned_lines))

    compressed_content = "\n\n".join(output_parts)

    # Trailing notice about removed stdlib imports
    if removed_imports:
        uniq = sorted(set(removed_imports))
        notice = (
            "\n\n# --- NOTE: stdlib imports were stripped during compression ---\n"
            "# Re-add them (or ensure they are globally available) before running:\n"
            + "\n".join(f"#   {imp}" for imp in uniq)
        )
        compressed_content += notice

    Path("compressed.txt").write_text(compressed_content, encoding="utf-8")
    cprint(
        f"Compressed {len(parsed_trees)} file(s); "
        f"removed {len(set(removed_imports))} stdlib import(s)."
    )


def get_python_files():
    return [str(p) for p in Path(".").rglob("*.py") if p.is_file()]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        files = get_python_files()
        if not files:
            print("No Python files found in current directory.")
            sys.exit(0)
        print(f"Processing {len(files)} Python files from current directory...")
        compress_files(files)
    else:
        compress_files(sys.argv[1:])
