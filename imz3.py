#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
from pathlib import Path

from dh import get_files


def extract_imports_from_py(code: str, base_path: Path | None = None) -> set[str]:
    results = set()
    try:
        tree = ast.parse(code)
    except Exception:
        return results
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mod = a.name.split(".", 1)[0]
                if mod not in STDLIB:
                    results.add(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                if base_path is not None:
                    module_str = "." * node.level
                    if node.module:
                        module_str += node.module
                    if is_local_module(base_path, module_str):
                        continue
                if node.module:
                    continue
                continue
            if node.module:
                mod = node.module.split(".", 1)[0]
                if mod not in STDLIB:
                    results.add(mod)
    return results


def is_local_module(base_path: Path, module: str) -> bool:
    dots = len(module) - len(module.lstrip("."))
    mod = module.lstrip(".")
    parent = base_path.parent
    for _ in range(dots - 1):
        parent = parent.parent
    pkg_dir = parent / mod.replace(".", "/")
    if (pkg_dir / "__init__.py").exists():
        return True
    py_file = pkg_dir.with_suffix(".py")
    return bool(py_file.exists())


def main() -> None:
    cwd = Path.cwd()
    importz = []
    for file in get_files(cwd, ext=[".py"]):
        with Path(file).open(encoding="utf-8") as f:
            contents = f.read()
            importz.append(extract_imports_from_py(contents))
    with Path("importz.txt").open("w", encoding="utf-8") as fo:
        for im in importz:
            fo.writelines(str(k) + "\n" for k in im)


if __name__ == "__main__":
    raise SystemExit(main())
