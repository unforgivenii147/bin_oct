#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import tree_sitter_python as tsp
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tsp.language())
parser = Parser(PY_LANGUAGE)


def get_ast_sexp(node, source: bytes, depth: int = 0) -> str:
    if node.child_count == 0:
        token = source[node.start_byte : node.end_byte].decode("utf-8")
        return f'({node.type} "{token}")'
    children_sexp = " ".join(
        get_ast_sexp(child, source, depth + 1) for child in node.children
    )
    return f"({node.type} {children_sexp})"


def parse_and_generate(code: str) -> str:
    tree = parser.parse(code.encode("utf-8"))
    return get_ast_sexp(tree.root_node, code.encode("utf-8"))


result = parse_and_generate(code)
print(result)
