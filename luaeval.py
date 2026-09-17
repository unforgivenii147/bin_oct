#!/data/data/com.termux/files/home/.local/bin/python
"""
Scan Lua files recursively and move files with syntax errors
to an 'error' subdirectory in their parent folder.
"""

from pathlib import Path

import tree_sitter_lua
from tree_sitter import Language, Parser


def make_parser() -> Parser:
    """Create a tree-sitter parser for Lua."""
    language = Language(tree_sitter_lua.language())
    return Parser(language)


def has_syntax_error(parser: Parser, source: bytes) -> bool:
    """Return True if the source has any syntax errors."""
    tree = parser.parse(source)
    # Walk the tree and look for ERROR or MISSING nodes
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            return True
        stack.extend(node.children)
    return False


def move_to_error_dir(path: Path) -> None:
    """Move file to an 'error' subdir in its parent folder."""
    error_dir = path.parent / "error"
    error_dir.mkdir(exist_ok=True)
    target = error_dir / path.name
    # Avoid overwriting: append a numeric suffix if needed
    if target.exists():
        i = 1
        while True:
            candidate = error_dir / f"{path.stem}_{i}{path.suffix}"
            if not candidate.exists():
                target = candidate
                break
            i += 1
    path.rename(target)
    print(f"Moved: {path} -> {target}")


def main() -> None:
    parser = make_parser()
    cwd = Path.cwd()

    for lua_file in cwd.rglob("*.lua"):
        # Skip files already inside an 'error' directory
        if "error" in lua_file.parts:
            continue
        try:
            source = lua_file.read_bytes()
        except OSError as e:
            print(f"Could not read {lua_file}: {e}")
            continue

        if has_syntax_error(parser, source):
            move_to_error_dir(lua_file)
        else:
            print(f"OK: {lua_file}")


if __name__ == "__main__":
    main()
