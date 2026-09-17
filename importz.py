#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import sys
from pathlib import Path


def is_python_file(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.is_file() and not path.suffix:
        try:
            with Path(path).open(encoding="utf-8") as f:
                first_line = f.readline()
                return "python" in first_line
        except Exception:
            return False
    return False


def get_imports_from_file(path: Path):
    imports = set()
    try:
        with Path(path).open(encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
    except (SyntaxError, UnicodeDecodeError):
        pass
    return imports


def main() -> None:
    cwd = Path()
    output_file = cwd / "importz.txt"
    all_imports = set()
    local_names = {p.stem for p in cwd.glob("*.py")}
    local_names.update(
        {p.name for p in cwd.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    )
    std_libs = getattr(sys, "stdlib_module_names", set())
    for path in cwd.rglob("*"):
        if is_python_file(path) and path.name != "importz.txt":
            all_imports.update(get_imports_from_file(path))
    third_party = sorted(
        [
            imp
            for imp in all_imports
            if imp not in std_libs and imp not in local_names and imp != "__future__"
        ]
    )
    if third_party:
        output_file.write_text("\n".join(third_party), encoding="utf-8")
        print(f"✅ Saved {len(third_party)} 3rd-party imports to {output_file}")
    else:
        print("ℹ️ No 3rd-party imports found.")


if __name__ == "__main__":
    raise SystemExit(main())
