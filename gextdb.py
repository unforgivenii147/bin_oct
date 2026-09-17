#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path("output")
DB_PATH = Path("/sdcard/ext.db")
ALLOWED_PYTHON_EXTENSIONS = ".py", ""


class EntityExtractor(ast.NodeVisitor):
    def __init__(self, source_content: str, original_path: Path) -> None:
        self.entities = []
        self.source_lines = source_content.splitlines(keepends=True)
        self.original_path = original_path
        self.scope_stack = []

    def _get_source_slice(self, node: ast.AST) -> str:
        start_line = node.lineno - 1
        end_line = node.end_lineno or node.lineno
        code_slice = self.source_lines[start_line:end_line]
        if node.col_offset is not None:
            code_slice[0] = code_slice[0][node.col_offset :]
        if node.end_col_offset is not None and node.end_col_offset > 0:
            last_line = code_slice[-1]
            code_slice[-1] = last_line[: node.end_col_offset]
        return "".join(code_slice)

    def _extract_and_save(self, node: ast.AST, entity_type: str, name: str) -> None:
        entity_code = self._get_source_slice(node)
        scope_prefix = "_".join(self.scope_stack)
        full_name = f"{scope_prefix}_{name}" if scope_prefix else name
        self.entities.append(
            {
                "name": name,
                "full_name": full_name,
                "type": entity_type,
                "code": entity_code,
                "path": str(self.original_path),
                "is_constant": entity_type == "constant",
                "is_class": entity_type == "class",
                "is_function": entity_type in {"function", "method"},
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self.scope_stack:
            self._extract_and_save(node, "function", node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._extract_and_save(node, "class", node.name)
        self.scope_stack.append(f"class_{node.name}")
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        if (
            not self.scope_stack
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            if re.match(r"^[A-Z_][A-Z0-9_]*$", target_name):
                self._extract_and_save(node, "constant", target_name)

    def generic_visit(self, node: ast.AST) -> None:
        super().generic_visit(node)


class EntityExtractor(ast.NodeVisitor):
    def __init__(self, source_content: str, original_path: Path) -> None:
        self.entities = []
        self.source_lines = source_content.splitlines(keepends=True)
        self.original_path = original_path
        self.scope_stack = []

    def _get_source_slice(self, node: ast.AST) -> str:
        start_line = node.lineno - 1
        end_line = node.end_lineno or node.lineno
        code_slice = self.source_lines[start_line:end_line]
        if node.col_offset is not None:
            code_slice[0] = code_slice[0][node.col_offset :]
        if node.end_col_offset is not None and node.end_col_offset > 0:
            last_line = code_slice[-1]
            code_slice[-1] = last_line[: node.end_col_offset]
        return "".join(code_slice)

    def _extract_and_save(self, node: ast.AST, entity_type: str, name: str) -> None:
        entity_code = self._get_source_slice(node)
        scope_prefix = "_".join(self.scope_stack)
        full_name = f"{scope_prefix}_{name}" if scope_prefix else name
        self.entities.append(
            {
                "name": name,
                "full_name": full_name,
                "type": entity_type,
                "code": entity_code,
                "path": str(self.original_path),
                "is_constant": entity_type == "constant",
                "is_class": entity_type == "class",
                "is_function": entity_type in {"function", "method"},
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        entity_type = (
            "method"
            if self.scope_stack and self.scope_stack[-1].startswith("class_")
            else "function"
        )
        self._extract_and_save(node, entity_type, node.name)
        self.scope_stack.append(f"func_{node.name}")
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        entity_type = (
            "method"
            if self.scope_stack and self.scope_stack[-1].startswith("class_")
            else "function"
        )
        self._extract_and_save(node, entity_type, node.name)
        self.scope_stack.append(f"async_func_{node.name}")
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._extract_and_save(node, "class", node.name)
        self.scope_stack.append(f"class_{node.name}")
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        if (
            not self.scope_stack
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            if re.match(r"^[A-Z_][A-Z0-9_]*$", target_name):
                self._extract_and_save(node, "constant", target_name)

    def generic_visit(self, node: ast.AST) -> None:
        super().generic_visit(node)


def create_database() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            full_name TEXT,
            type TEXT,
            code TEXT,
            path TEXT,
            is_constant BOOLEAN,
            is_class BOOLEAN,
            is_function BOOLEAN
        )
    """)
    conn.commit()
    conn.close()


def save_entity_to_db(entity: dict[str, Any]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO entities (name, full_name, type, code, path, is_constant, is_class, is_function)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            entity["name"],
            entity["full_name"],
            entity["type"],
            entity["code"],
            entity["path"],
            entity["is_constant"],
            entity["is_class"],
            entity["is_function"],
        ),
    )
    conn.commit()
    conn.close()


def extract_entities_from_content(content: str, path: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
        extractor = EntityExtractor(content, path)
        extractor.visit(tree)
        return extractor.entities
    except SyntaxError:
        return []
    except Exception as e:
        print(f"Error parsing AST for {path}: {e}")
        return []


def is_python_file_no_extension(path: Path) -> bool:
    if path.suffix:
        return False
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            first_lines = "".join(f.readlines(1024))
            return bool(
                re.match(r"#!\s*/.*python", first_lines)
                or (
                    "def " in first_lines
                    or "class " in first_lines
                    or "import " in first_lines
                )
            )
    except:
        return False


def process_single_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".py" or is_python_file_no_extension(path):
            content = path.read_text(encoding="utf-8", errors="ignore")
            return extract_entities_from_content(content, path)
        return []
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Python entities and save to database."
    )
    parser.add_argument(
        "-db",
        "--database",
        action="store_true",
        help="Save extracted entities to the database",
    )
    args = parser.parse_args()
    print(f"Starting analysis in {Path.cwd()}...")
    create_database()
    files_to_process = []
    cwd = Path()
    for root, _, filenames in os.walk(cwd):
        for name in filenames:
            path = Path(root) / name
            if path.is_relative_to(OUTPUT_DIR):
                continue
            if path.suffix in ALLOWED_PYTHON_EXTENSIONS or is_python_file_no_extension(
                path
            ):
                files_to_process.append(path)
    if not files_to_process:
        print("No Python files found to process.")
        return
    all_entities = []
    for path in files_to_process:
        entities = process_single_file(path)
        all_entities.extend(entities)
    print(f"Processing complete. Extracted {len(all_entities)} entities.")
    if args.database:
        print(f"Saving entities to database at {DB_PATH}...")
        for entity in all_entities:
            save_entity_to_db(entity)
        print("All entities saved to database.")
    print("All tasks finished successfully!")


if __name__ == "__main__":
    raise SystemExit(main())
