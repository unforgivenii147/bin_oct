#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import os
from pathlib import Path

OUTPUT_FILE = "found.txt"


def is_probably_python(path: str) -> bool:
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            head = f.read(2048)
        return "import " in head or "def " in head or "class " in head
    except Exception:
        return False


def has_late_import(path: str) -> bool:
    try:
        code = Path(path).read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(code)
    except Exception:
        return False
    seen_non_import = False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not seen_non_import:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and seen_non_import:
            return True
        seen_non_import = True
    return False


def find_files(root: str) -> list[str]:
    results = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if not name.endswith(".py") and not is_probably_python(path):
                continue
            if has_late_import(path):
                results.append(os.path.relpath(path, root))
    return sorted(results)


def main() -> None:
    matches = find_files(Path.cwd())
    with Path(OUTPUT_FILE).open("w", encoding="utf-8") as f:
        f.writelines(path + "\n" for path in matches)
    print(f"Found {len(matches)} files with late imports.")
    print(f"Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    raise SystemExit(main())
