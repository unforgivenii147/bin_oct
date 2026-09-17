#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import copy
import hashlib
import sys
from ast import AsyncFunctionDef, ClassDef, FunctionDef
from dataclasses import dataclass
from pathlib import Path

from dh import get_pyfiles, gsz, mpf3


@dataclass
class Decl:
    kind: str
    name: str
    lineno: int
    end_lineno: int
    source: str
    content_hash: str


class Normalizer(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node = copy.deepcopy(node)
        node.name = "__NAME__"
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node = copy.deepcopy(node)
        node.name = "__NAME__"
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        node = copy.deepcopy(node)
        node.name = "__NAME__"
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        node = copy.deepcopy(node)
        if isinstance(node.ctx, ast.Store):
            return node


def stable_hash(node: ast.AST) -> str:
    node = copy.deepcopy(node)
    node = Normalizer().visit(node)
    ast.fix_missing_locations(node)
    dumped = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def get_source_segment(lines, lineno, end_lineno) -> str:
    return "".join(lines[lineno - 1 : end_lineno])


def is_simple_top_level_assign(node) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    for target in node.targets:
        if isinstance(target, ast.Name):
            continue
        if isinstance(target, (ast.Tuple, ast.List)):
            return False
        return False
    return True


def extract_assign_names(node):
    names = []
    for target in node.targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def build_decl_for_assign(node, lines):
    names = extract_assign_names(node)
    source = get_source_segment(lines, node.lineno, node.end_lineno)
    h = stable_hash(node)
    decls = []
    for name in names:
        decls.append(
            Decl(
                kind="assign",
                name=name,
                lineno=node.lineno,
                end_lineno=node.end_lineno,
                source=source,
                content_hash=h,
            )
        )
    return decls


def build_decl(
    node: AsyncFunctionDef | ClassDef | FunctionDef, kind: str, name: str, lines
) -> Decl:
    return Decl(
        kind=kind,
        name=name,
        lineno=node.lineno,
        end_lineno=node.end_lineno,
        source=get_source_segment(lines, node.lineno, node.end_lineno),
        content_hash=stable_hash(node),
    )


def process_file(src_path) -> None:
    Path(path)
    dup_path = src_path.parent / f"{src_path.stem}_dups.py"
    text = src_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        print(f"Syntax error in {src_path}: {e}")
        sys.exit(1)
    decls = []
    top_level_nodes = []
    for node in tree.body:
        if is_simple_top_level_assign(node):
            decls.extend(build_decl_for_assign(node, lines))
            top_level_nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decls.append(build_decl(node, "function", node.name, lines))
            top_level_nodes.append(node)
        elif isinstance(node, ast.ClassDef):
            decls.append(build_decl(node, "class", node.name, lines))
            top_level_nodes.append(node)
    seen_name = set()
    seen_hash = set()
    duplicate_ranges = []
    duplicate_reasons = []
    already_marked_ranges = set()
    for decl in decls:
        key_name = (decl.kind, decl.name)
        key_hash = (decl.kind, decl.content_hash)
        rng = (decl.lineno, decl.end_lineno)
        is_dup = False
        reason = None
        if key_name in seen_name:
            is_dup = True
            reason = f"duplicate {decl.kind} name: {decl.name}"
        elif key_hash in seen_hash:
            is_dup = True
            reason = f"duplicate {decl.kind} content hash: {decl.name}"
        else:
            seen_name.add(key_name)
            seen_hash.add(key_hash)
        if is_dup and rng not in already_marked_ranges:
            duplicate_ranges.append(rng)
            duplicate_reasons.append((decl, reason))
            already_marked_ranges.add(rng)
    if not duplicate_ranges:
        print("No duplicate top-level assignments/functions/classes found.")
        return
    remove_lines = set()
    for start, end in duplicate_ranges:
        remove_lines.update(range(start, end + 1))
    kept_lines = [
        line for i, line in enumerate(lines, start=1) if i not in remove_lines
    ]
    out = []
    out.append(f"\n# Duplicates moved from {src_path.name}\n")
    for decl, reason in duplicate_reasons:
        out.append(f"\n# {reason} @ lines {decl.lineno}-{decl.end_lineno}\n")
        out.append(decl.source)
        if not decl.source.endswith("\n"):
            out.append("\n")
    src_path.write_text("".join(kept_lines), encoding="utf-8")
    with dup_path.open("a", encoding="utf-8") as f:
        f.write("".join(out))
    print(f"Updated {src_path} in place")
    print(f"Moved {len(duplicate_ranges)} duplicate declaration block(s) to {dup_path}")


def main() -> None:
    cwd = Path.cwd()
    gsz(cwd)
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_pyfiles(p))
    else:
        files = get_pyfiles(cwd)
    results = mpf3(process_file, files)
    for result in results:
        if result:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
