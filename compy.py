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


class StripDocstringsAndTypes(ast.NodeTransformer):
    """Removes docstrings, function return types, parameter type hints, and type annotations."""

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
        # Convert annotated assignment `x: int = 1` -> `x = 1`
        if node.value is None:
            return None  # Drop variable declarations without values (e.g., `x: int`)
        return self.visit(ast.Assign(targets=[node.target], value=node.value))

    def _remove_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)


def generate_short_names():
    """Generates short variable names: a, b, ..., z, a1, b1, ..."""
    letters = string.ascii_lowercase
    idx = 0
    while True:
        if idx < 26:
            yield letters[idx]
        else:
            yield f"{letters[idx % 26]}{idx // 26}"
        idx += 1


class NameCollector(ast.NodeVisitor):
    """Collects user-defined identifiers longer than 3 characters."""

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
    """Replaces collected identifiers with shortened names."""

    def __init__(self, name_map):
        self.name_map = name_map

    def visit_FunctionDef(self, node):
        node.name = self.name_map.get(node.name, node.name)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.name = self.name_map.get(node.name, node.name)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        node.name = self.map_or_self(node.name)
        self.generic_visit(node)
        return node

    def map_or_self(self, name):
        return self.name_map.get(name, name)

    def visit_arg(self, node):
        node.arg = self.name_map.get(node.arg, node.arg)
        return node

    def visit_Name(self, node):
        node.id = self.name_map.get(node.id, node.id)
        return node


def compress_files(file_paths):
    name_map = {}
    name_gen = generate_short_names()
    parsed_trees = []

    # First pass: Parse AST and collect identifiers across all files
    for filepath in file_paths:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: File '{filepath}' not found. Skipping.", file=sys.stderr)
            continue

        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=filepath)

        # Strip types and docstrings
        tree = StripDocstringsAndTypes().visit(tree)
        ast.fix_missing_locations(tree)

        # Collect variable/function names for shortening
        NameCollector(name_map, name_gen).visit(tree)
        parsed_trees.append((filepath, tree))

    # Second pass: Rename identifiers and generate compressed code
    output_parts = []
    for filepath, tree in parsed_trees:
        tree = NameRenamer(name_map).visit(tree)
        ast.fix_missing_locations(tree)

        # ast.unparse removes comments and formats clean python
        minified_code = ast.unparse(tree)

        # Strip out empty lines
        cleaned_lines = [line for line in minified_code.splitlines() if line.strip()]
        header = f"# --- File: {filepath} ---"
        output_parts.append(header + "\n" + "\n".join(cleaned_lines))

    # Save output
    compressed_content = "\n\n".join(output_parts)
    Path("compressed.txt").write_text(compressed_content, encoding="utf-8")
    cprint(f"Compressed {len(parsed_trees)} file(s).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compressor.py <file1.py> [file2.py ...]")
        sys.exit(1)

    compress_files(sys.argv[1:])
