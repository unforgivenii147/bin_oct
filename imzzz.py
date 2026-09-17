#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import multiprocessing as mp
import os
import tarfile
import zipfile
from pathlib import Path

from dh import PKG_MAPPING, STDLIB

STD_LIB = STDLIB
MAPPING = PKG_MAPPING
try:
    with Path("/sdcard/pip.txt").open("r", encoding="utf-8") as f:
        PIP_PACKAGES = {
            line.strip().split("==")[0].split("[")[0] for line in f if line.strip()
        }
except FileNotFoundError:
    PIP_PACKAGES = set()


def is_python_file(path):
    return path.suffix == ".py" or (
        not path.suffix
        and any(
            line.startswith(("import ", "from ", "#!/usr/bin/env python"))
            for line in Path(path).open(encoding="utf-8", errors="ignore")
        )
    )


def extract_compressed(path, extract_to) -> None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(extract_to)
    elif path.suffix in {".tar.gz", ".tar.xz", ".tar.zst"}:
        with tarfile.open(path, "r:*") as tar:
            tar.extractall(extract_to)
    elif path.suffix == ".whl":
        with zipfile.ZipFile(path, "r") as z:
            z.extractall(extract_to)


def get_imports(path):
    imports = set()
    try:
        with Path(path).open(encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if (
                    module not in STD_LIB
                    and not module.startswith(".")
                    and not path.parent.match(f"*{module}*")
                ):
                    imports.add(MAPPING.get(module, module))
        elif isinstance(node, ast.ImportFrom):
            module = node.module.split(".")[0] if node.module else ""
            if (
                module
                and module not in STD_LIB
                and not module.startswith(".")
                and not path.parent.match(f"*{module}*")
            ):
                imports.add(MAPPING.get(module, module))
    return imports


def process_file(path):
    Path(path)
    if path.is_dir():
        return set()
    if path.suffix in {".zip", ".whl", ".tar.gz", ".tar.xz", ".tar.zst"}:
        extract_dir = path.parent / f"extracted_{path.stem}"
        extract_compressed(path, extract_dir)
        imports = set()
        for root, _, files in os.walk(extract_dir):
            for f in files:
                f_path = Path(root) / f
                if is_python_file(f_path):
                    imports.update(get_imports(f_path))
        return imports
    if is_python_file(path):
        return get_imports(path)
    return set()


def main() -> None:
    root = Path()
    python_files = []
    for ext in ("*.py", "*"):
        python_files.extend(root.rglob(ext))
    with mp.Pool() as pool:
        results = pool.map(process_file, python_files)
    all_imports = set().union(*results)
    requirements = sorted(all_imports & PIP_PACKAGES)
    with Path("requirements.txt").open("w", encoding="utf-8") as f:
        f.writelines(f"{req}\n" for req in requirements)


if __name__ == "__main__":
    raise SystemExit(main())
