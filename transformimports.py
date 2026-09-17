#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any


class ImportTransformer(ast.NodeTransformer):
    def __init__(self, tree: ast.Module):
        self.tree = tree
        self.module_to_names: dict[str, set[str]] = {}
        self.modified = False
        self._analyze_usage()

    def _analyze_usage(self) -> None:
        direct_imports = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.asname:
                        direct_imports.add(alias.name)
        if not direct_imports:
            return
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in direct_imports:
                    self.module_to_names.setdefault(node.value.id, set()).add(node.attr)

    def visit_Import(self, node: ast.Import) -> Any:
        new_nodes = []
        for alias in node.names:
            if not alias.asname and alias.name in self.module_to_names:
                self.modified = True
                names = sorted(self.module_to_names[alias.name])
                new_nodes.append(
                    ast.ImportFrom(
                        module=alias.name,
                        names=[ast.alias(name=n, asname=None) for n in names],
                        level=0,
                    )
                )
            else:
                new_nodes.append(ast.Import(names=[alias]))
        return new_nodes if len(new_nodes) > 1 else new_nodes[0] if new_nodes else None

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        if isinstance(node.value, ast.Name) and node.value.id in self.module_to_names:
            self.modified = True
            return ast.Name(id=node.attr, ctx=node.ctx)
        return self.generic_visit(node)


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python transformimports_optimized.py <python_file>", file=sys.stderr
        )
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists() or path.suffix != ".py":
        print(f"Error: Invalid Python file '{path}'", file=sys.stderr)
        sys.exit(1)
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        transformer = ImportTransformer(tree)
        new_tree = transformer.visit(tree)
        if transformer.modified:
            ast.fix_missing_locations(new_tree)
            new_content = ast.unparse(new_tree)
            path.write_text(new_content, encoding="utf-8")
            print(f"✓ Successfully transformed imports in '{path}'.")
        else:
            print(f"No transformations needed for '{path}'.")
    except SyntaxError as e:
        print(f"Error: File has syntax errors: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
