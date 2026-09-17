#!/data/data/com.termux/files/home/.local/bin/python
"""
Inspect .py files in the current folder and report ones missing the main guard.
"""

import ast
import sys
from pathlib import Path


def has_main_guard(filepath: Path) -> bool:
    """Return True if the file contains an `if __name__ == '__main__':` block."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"  ! Could not read {filepath.name}: {e}", file=sys.stderr)
        return True  # Don't flag files we can't read

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"  ! Syntax error in {filepath.name}: {e}", file=sys.stderr)
        return True  # Don't flag unparseable files

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Match: __name__ == "__main__"  (or reversed, or != is wrong but we only want ==)
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        left, right = test.left, test.comparators[0]

        def is_dunder_name(n):
            return isinstance(n, ast.Name) and n.id == "__name__"

        def is_main_string(n):
            return isinstance(n, ast.Constant) and n.value == "__main__"

        if (is_dunder_name(left) and is_main_string(right)) or (
            is_dunder_name(right) and is_main_string(left)
        ):
            return True

    return False


def main():
    from fastwalk import walk_files

    cwd = Path.cwd()
    for p in walk_files(cwd):
        if p.is_file() and p.suffix == ".py" and p.name != Path(__file__).name:
            if not has_main_guard(p):
                print(p.name)


#                break


if __name__ == "__main__":
    sys.exit(main())
