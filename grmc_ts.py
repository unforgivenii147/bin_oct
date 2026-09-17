#!/data/data/com.termux/files/home/.local/bin/python
"""
Strip comments and docstrings from Python source files using tree-sitter.
Preserves shebang lines, `# type:` directives, and `# fmt:` pragmas while
removing all other comments and module/function/class docstrings. Discovers
targets from CLI path arguments (defaults to CWD), processes them in a fixed
multiprocessing.Pool of 8 workers, validates each result with ast.parse, and
reports per-file status via loguru.
"""

import argparse
import ast
import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import tree_sitter_python as tspython  # type: ignore[import-untyped]
from tree_sitter import Language, Parser, Tree, TreeCursor  # type: ignore[import-untyped]

MAX_WORKERS: Final[int] = 8
PRESERVE_PREFIXES: Final[tuple[str, ...]] = ("#!", "# type:", "# fmt:")
PRESERVE_EXACT: Final[frozenset[str]] = frozenset(
    {"# fmt: skip", "# fmt: on", "# fmt: off"}
)

PY_LANGUAGE: Final[Language] = Language(tspython.language())

Removal = tuple[int, int, bytes]


def get_parser() -> Parser:
    """
    Build a tree-sitter parser configured for Python.

    Returns:
        A fresh :class:`Parser` bound to :data:`PY_LANGUAGE`.
    """
    return Parser(PY_LANGUAGE)


def should_preserve_comment(comment_bytes: bytes) -> bool:
    """
    Decide whether a comment must be preserved during stripping.

    Preserves shebang lines, PEP 484 type directives, and Black/isort fmt
    pragmas.

    Args:
        comment_bytes: Raw comment bytes including the leading ``#``.

    Returns:
        ``True`` if the comment should be kept, ``False`` otherwise.
    """
    text: str = comment_bytes.decode("utf-8", errors="ignore").strip()
    return text.startswith(PRESERVE_PREFIXES) or text in PRESERVE_EXACT


def process_file(file_path: Path) -> str:
    """
    Strip comments and docstrings from a single Python file in place.

    Parses the file with tree-sitter, collects byte-range replacements for
    every non-preserved comment and every docstring (module-level or nested
    inside a function/class body), applies the replacements, and validates
    the result with :func:`ast.parse` before writing.

    Args:
        file_path: Path to the Python source file to process.

    Returns:
        A human-readable status message prefixed with ``[SUCCESS]``,
        ``[SKIPPED]``, ``[WARNING]``, or ``[ERROR]``.
    """
    try:
        source_bytes: bytes = file_path.read_bytes()
    except Exception as exc:
        return f"[ERROR] Failed to read {file_path}: {exc}"

    parser: Parser = get_parser()
    tree: Tree = parser.parse(source_bytes)
    root = tree.root_node

    removals: list[Removal] = []

    module_docstring_node: object | None = None
    if root.child_count > 0:
        first_child = root.child(0)
        if first_child is not None and first_child.type == "expression_statement":
            expr_child = first_child.child(0)
            if expr_child is not None and expr_child.type == "string":
                module_docstring_node = first_child

    cursor: TreeCursor = tree.walk()
    reached_end: bool = False
    while not reached_end:
        node = cursor.node
        if node.type == "comment":
            node_bytes: bytes = source_bytes[node.start_byte : node.end_byte]
            if not should_preserve_comment(node_bytes):
                removals.append((node.start_byte, node.end_byte, b""))
        elif node.type == "expression_statement" and node != module_docstring_node:
            expr_child = node.child(0)
            if expr_child is not None and expr_child.type == "string":
                parent = node.parent
                if parent is not None and parent.type == "block":
                    if parent.named_child_count == 1:
                        removals.append((node.start_byte, node.end_byte, b"pass"))
                    else:
                        removals.append((node.start_byte, node.end_byte, b""))

        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached_end = True
                break
            if cursor.goto_next_sibling():
                break

    if not removals:
        return f"[SKIPPED] No structural modifications needed for {file_path}"

    removals.sort(key=lambda item: item[0], reverse=True)
    modified_bytes: bytearray = bytearray(source_bytes)
    for start, end, replacement in removals:
        modified_bytes[start:end] = replacement

    final_code: bytes = bytes(modified_bytes)

    try:
        ast.parse(final_code, filename=str(file_path))
    except SyntaxError as exc:
        return f"[WARNING] Validation failed for {file_path} (Changes rejected): {exc}"

    try:
        file_path.write_bytes(final_code)
        return f"[SUCCESS] Processed and stripped: {file_path}"
    except Exception as exc:
        return f"[ERROR] Failed to save updates to {file_path}: {exc}"


def gather_files(inputs: list[str]) -> list[Path]:
    """
    Resolve the list of ``.py`` files to process.

    Args:
        inputs: Raw CLI path arguments. If empty, the current working
            directory is searched recursively.

    Returns:
        A sorted, de-duplicated list of ``.py`` file paths.
    """
    files: set[Path] = set()

    if not inputs:
        files.update(Path(".").rglob("*.py"))
        return sorted(files)

    for item in inputs:
        p: Path = Path(item)
        if p.is_file() and p.suffix == ".py":
            files.add(p)
        elif p.is_dir():
            files.update(p.rglob("*.py"))

    return sorted(files)


def main() -> None:
    """Parse CLI arguments and process each target file in parallel."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Strip comments and docstrings using Tree-Sitter safely."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Target files or directories to process. Defaults to '.' if empty.",
    )
    args: argparse.Namespace = parser.parse_args()

    targets: list[Path] = gather_files(args.paths)
    if not targets:
        print("No target Python source files detected.")
        sys.exit(0)

    print(
        f"Queue loaded. Processing {len(targets)} target files via Parallel Pipeline..."
    )

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[str]] = [
            pool.apply_async(process_file, (target,)) for target in targets
        ]
        for async_res in async_results:
            result_string: str = async_res.get()
            print(result_string)


if __name__ == "__main__":
    raise SystemExit(main())
