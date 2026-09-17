#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from ast import Call
from pathlib import Path

from dh import get_pyfiles

TARGET_FUNCS = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "findall",
    "finditer",
    "split",
    "sub",
    "subn",
}


class RegexFixer(ast.NodeTransformer):
    def visit_Call(self, node: ast.Call) -> Call:
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
            and node.func.attr in TARGET_FUNCS
            and node.args
        ):
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                original = first_arg.value
                fixed = original.encode("unicode_escape").decode("ascii")
                fixed = fixed.replace(r"\\n", r"\n")
                fixed = fixed.replace(r"\\t", r"\t")
                fixed = fixed.replace(r"\\r", r"\r")
                node.args[0] = ast.Constant(value=fixed)
                print(f"{original}\n{fixed}\n\n")
        return node


def fix_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        print(f"[SKIP] {path} (syntax error)")
        return False
    fixer = RegexFixer()
    new_tree = fixer.visit(tree)
    ast.fix_missing_locations(new_tree)
    new_source = ast.unparse(new_tree)
    if new_source != source:
        path.write_text(new_source, encoding="utf-8")
        print(f"[FIXED] {path}")
        return True
    return False


def main() -> None:
    cwd = Path()
    files = get_pyfiles(cwd)
    changed = 0
    for f in files:
        if fix_file(f):
            changed += 1
    print(f"\nDone. Modified {changed} files.")


if __name__ == "__main__":
    raise SystemExit(main())
