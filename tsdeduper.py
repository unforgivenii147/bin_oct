#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser

OUTPUT_FILE = "utils.py"


@dataclass(frozen=True)
class Item:
    kind: str
    name: str
    source: str
    path: str
    hash: str


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_parser() -> Parser:
    parser = Parser()
    parser.language = Language(tsp.language())
    return parser


def node_text(src: bytes, node: Node) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def is_const_name(name: str) -> bool:
    return name.isupper()


def extract_items(path: Path, parser: Parser) -> list[Item]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    src = text.encode("utf-8", errors="replace")
    tree = parser.parse(src)
    root = tree.root_node
    items: list[Item] = []
    for node in root.children:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = node_text(src, name_node)
            code = node_text(src, node)
            items.append(
                Item(
                    kind="function",
                    name=name,
                    source=code,
                    path=str(path),
                    hash=sha256_text(code),
                )
            )
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = node_text(src, name_node)
            code = node_text(src, node)
            items.append(
                Item(
                    kind="class",
                    name=name,
                    source=code,
                    path=str(path),
                    hash=sha256_text(code),
                )
            )
        elif node.type in {"expression_statement", "assignment"}:
            code = node_text(src, node)
            assign_node = node
            if node.type == "expression_statement" and node.children:
                assign_node = node.children[0]
            if assign_node.type != "assignment":
                continue
            if len(assign_node.children) < 3:
                continue
            lhs = assign_node.children[0]
            if lhs.type != "identifier":
                continue
            name = node_text(src, lhs)
            if not is_const_name(name):
                continue
            items.append(
                Item(
                    kind="const",
                    name=name,
                    source=code,
                    path=str(path),
                    hash=sha256_text(code),
                )
            )
    return items


def write_utils_file(dups: dict[str, Item], output: Path) -> None:
    lines = [
        "# Auto-generated file",
        "# Contains duplicate top-level constants, functions, and classes.",
        "",
    ]
    seen = set()
    for h, item in dups.items():
        if h in seen:
            continue
        seen.add(h)
        lines.append(f"# Duplicate {item.kind}: {item.name}")
        lines.append(f"# Source: {item.path}")
        lines.append(item.source)
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = make_parser()
    base = Path.cwd()
    seen: dict[str, Item] = {}
    dups: dict[str, Item] = {}
    for root, _, files in os.walk(base):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            if fname == OUTPUT_FILE:
                continue
            path = Path(root) / fname
            for item in extract_items(path, parser):
                if item.hash in seen:
                    dups[item.hash] = seen[item.hash]
                else:
                    seen[item.hash] = item
    out = base / OUTPUT_FILE
    if dups:
        write_utils_file(dups, out)
        print(f"Found {len(dups)} duplicate items.")
        print(f"Wrote them to: {out}")
    else:
        print("No duplicates found.")


if __name__ == "__main__":
    raise SystemExit(main())
