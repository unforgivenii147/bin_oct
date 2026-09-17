#!/data/data/com.termux/files/home/.local/bin/python
"""
Print the tree-sitter AST (s-expression form) of one or more Python files.

For each input file, the script parses it with tree-sitter-python and prints
a fully-expanded s-expression of the syntax tree, including leaf tokens.

Usage
-----
    script.py FILE [FILE ...]

Each file is printed with a small header so multiple outputs stay readable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tree_sitter_python as tsp
from tree_sitter import Language, Parser

# ---------------------------------------------------------------------------
# Parser setup (module-level, shared across calls)
# ---------------------------------------------------------------------------
PY_LANGUAGE = Language(tsp.language())

# A single Parser instance is fine for sequential parsing. tree-sitter's
# Parser is *not* thread-safe, so if this script ever moves to a thread
# pool, each worker must create its own Parser.
_parser = Parser(PY_LANGUAGE)


# ---------------------------------------------------------------------------
# AST rendering
# ---------------------------------------------------------------------------
def get_ast_sexp(node, source: bytes, depth: int = 0) -> str:
    """
    Recursively render ``node`` and its descendants as an s-expression.

    Leaves (nodes with no children) are rendered as ``(type "token")`` so
    the actual source text is preserved. Interior nodes become
    ``(type child1 child2 ...)``.

    Args:
        node:    A tree-sitter ``Node``.
        source:  The original source bytes (used to slice leaf tokens).
        depth:   Recursion depth (unused, kept for API compatibility).

    Returns:
        A single-line s-expression string.
    """
    if node.child_count == 0:
        token = source[node.start_byte : node.end_byte].decode("utf-8")
        # Escape embedded double quotes so the output stays valid s-expr.
        token = token.replace('"', '\\"')
        return f'({node.type} "{token}")'

    children_sexp = " ".join(
        get_ast_sexp(child, source, depth + 1) for child in node.children
    )
    return f"({node.type} {children_sexp})"


def parse_and_generate(code: str) -> str:
    """
    Parse Python source text and return its s-expression representation.

    Args:
        code: Python source as a ``str``.

    Returns:
        The s-expression produced by :func:`get_ast_sexp`.
    """
    # Encode once and reuse — avoids encoding the same source twice.
    source_bytes = code.encode("utf-8")
    tree = _parser.parse(source_bytes)
    return get_ast_sexp(tree.root_node, source_bytes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def process_file(path: Path) -> int:
    """
    Parse a single file and print its AST.

    Returns:
        0 on success, 1 on any read/parse failure (so the caller can total
        the exit code across multiple inputs).
    """
    try:
        code = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as exc:
        print(f"error: {path} is not valid UTF-8: {exc}", file=sys.stderr)
        return 1

    try:
        result = parse_and_generate(code)
    except Exception as exc:  # noqa: BLE001 — tree-sitter failures are opaque
        print(f"error: failed to parse {path}: {exc}", file=sys.stderr)
        return 1

    # Header so multiple files stay distinguishable in the output stream.
    print(f"# {path}")
    print(result)
    return 0


def main() -> int:
    """Entry point: parse every file given on the command line."""
    parser = argparse.ArgumentParser(
        description="Print the tree-sitter AST of one or more Python files."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="One or more Python source files to parse.",
    )
    args = parser.parse_args()

    exit_code = 0
    for raw in args.files:
        path = Path(raw)
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            exit_code = 1
            continue
        if process_file(path) != 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    # ``raise SystemExit`` propagates the exit code cleanly.
    raise SystemExit(main())
