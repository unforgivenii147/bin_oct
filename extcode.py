#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tsp
from tree_sitter import Language, Parser

LANG = Language(tsp)
parser = Parser()
parser.set_language(LANG)
ROOT_DIR = Path.cwd()
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
VALID_TOP_LEVEL_NODES = {
    "function_definition",
    "class_definition",
    "import_statement",
    "import_from_statement",
    "assignment",
    "expression_statement",
    "if_statement",
    "for_statement",
    "while_statement",
    "try_statement",
    "with_statement",
}


def extract_from_file(py_file: Path) -> str:
    source = py_file.read_bytes()
    tree = parser.parse(source)
    root = tree.root_node
    extracted_chunks = [
        source[child.start_byte : child.end_byte].decode()
        for child in root.children
        if child.type in VALID_TOP_LEVEL_NODES
    ]
    return "\n\n".join(extracted_chunks)


def process_directory() -> None:
    for py_file in ROOT_DIR.rglob("*.py"):
        if any(part.startswith(".") for part in py_file.parts):
            continue
        if OUTPUT_DIR in py_file.parents:
            continue
        extracted = extract_from_file(py_file)
        if not extracted.strip():
            continue
        relative_path = py_file.relative_to(ROOT_DIR)
        out_file = OUTPUT_DIR / relative_path
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(extracted)
        print(f"Saved: {out_file}")


if __name__ == "__main__":
    process_directory()
