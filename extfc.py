#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Tree

parser = Parser()
parser.language = Language(tsp.language())
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)
VALID = {
    """
(expression_statement
  (assignment_expression
    (=( _ )@name value:value )
  )
  (
)"""
}


def get_node_text(src: bytes, node) -> str:
    return src[node.start_byte : node.end_byte].decode()


def extract_functions_and_classes(src: bytes, tree: Tree):
    root = tree.root_node
    definitions = []

    def traverse(node) -> None:
        if node.type in VALID:
            node_text = get_node_text(src, node)
            decorators = []
            prev_node = node.prev_sibling
            while prev_node and prev_node.type == "decorator":
                decorators.append(get_node_text(src, prev_node))
                prev_node = prev_node.prev_sibling
            if decorators:
                node_text = "\n".join(reversed(decorators)) + "\n" + node_text
            definitions.append(node_text)
        for child in node.children:
            traverse(child)

    traverse(root)
    return definitions


def get_relative_path(path: Path, base_path: Path) -> Path:
    try:
        return path.relative_to(base_path)
    except ValueError:
        return path


def extract_docstring(src: bytes, node) -> str | None:
    if node.children and node.children[0].type == "string":
        return get_node_text(src, node.children[0])
    return None


def format_definition_with_metadata(
    def_text: str, file_name: str, line_num: int, docstring: str | None = None
) -> str:
    lines = [f"# From: {file_name}:{line_num}"]
    if docstring:
        lines.append(
            f"# Docstring: {docstring[:50]}{'...' if len(docstring) > 50 else ''}"
        )
    lines.append(def_text)
    return "\n".join(lines)


folder_definitions = defaultdict(list)
processed_files_count = 0
folders_found = set()
total_definitions = 0
cwd = Path.cwd()
for py in cwd.rglob("*.py"):
    if any(part.startswith(".") for part in py.parts) or "site-packages" in py.parts:
        continue
    if OUT_DIR in py.parents:
        continue
    try:
        print(f"processing ... {py}")
        src = py.read_bytes()
        tree = parser.parse(src)
        definitions = extract_functions_and_classes(src, tree)
        if definitions:
            folder_path = py.parent
            relative_folder = get_relative_path(folder_path, Path())
            folders_found.add(str(relative_folder))
            file_header = f"\n# {'=' * 40}\n# File: {py.name}\n# {'=' * 40}\n"
            folder_definitions[relative_folder].append(file_header)
            for i, def_text in enumerate(definitions, 1):
                folder_definitions[relative_folder].append(def_text)
                if i < len(definitions):
                    folder_definitions[relative_folder].append(
                        "\n" + "#" + "-" * 58 + "\n"
                    )
            processed_files_count += 1
            total_definitions += len(definitions)
    except Exception as e:
        print(f"⚠️  Error processing {py}: {e}")
for folder, defs_list in folder_definitions.items():
    if not defs_list:
        continue
    out_file = OUT_DIR / folder / "definitions.py"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(defs_list)
    header = "#!/usr/bin/env python\n"
    out_file.write_text(header + content)
    folder_def_count = len(
        [
            d
            for d in defs_list
            if d.strip() and not d.startswith("#") and not d.startswith("\n#")
        ]
    )
    print(
        f"✅ saved: {out_file} ({folder_def_count} definitions from {len([f for f in defs_list if 'File:' in f])} files)"
    )
print(
    f"""
✨ Done! Processed {processed_files_count} files with {total_definitions} total definitions in {len(folder_definitions)} folder(s)"""
)
print(f"📁 Folders: {', '.join(sorted(folders_found))}")
