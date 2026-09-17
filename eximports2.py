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
VALID = {"import_statement", "import_from_statement"}


def extract_file(src: bytes, tree: Tree) -> list[str]:
    root = tree.root_node
    return [
        src[node.start_byte : node.end_byte].decode()
        for node in root.children
        if node.type in VALID
    ]


def get_relative_path(path: Path, base_path: Path) -> Path:
    try:
        return path.relative_to(base_path)
    except ValueError:
        return path


folder_imports = defaultdict(list)
processed_files_count = 0
folders_found = set()
for py in Path().rglob("*.py"):
    if any(part.startswith(".") for part in py.parts) or "site-packages" in py.parts:
        continue
    if OUT_DIR in py.parents:
        continue
    try:
        src = py.read_bytes()
        tree = parser.parse(src)
        imports = extract_file(src, tree)
        if imports:
            folder_path = py.parent
            relative_folder = get_relative_path(folder_path, Path())
            folders_found.add(str(relative_folder))
            file_header = f"# === {py.name} ===\n"
            folder_imports[relative_folder].append(file_header + "\n".join(imports))
            processed_files_count += 1
    except Exception as e:
        print(f"⚠️  Error processing {py}: {e}")
for folder, imports_list in folder_imports.items():
    if not imports_list:
        continue
    out_file = OUT_DIR / folder / "imports.py"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(imports_list)
    header = f"# Auto-generated imports file for folder: {folder}\n"
    out_file.write_text(header + content)
    print(f"✅ saved: {out_file} ({len(imports_list)} files)")
print(f"""
✨ Done! Processed {processed_files_count} files in {len(folder_imports)} folder(s)""")
print(f"📁 Folders: {', '.join(sorted(folders_found))}")
