#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate this script: a Python refactoring tool that inlines symbols imported from the local `dh` package into other Python files. It builds a symbol-to-file mapping from `dh/__init__.py`, parses each target file with `ast`, finds `from dh import ...` (and `import dh`) statements, recursively resolves the needed top-level symbols and their intra-file dependencies, collects any non-`dh` imports they require, removes the original `dh` imports, and injects the resolved imports and source blocks after the file's last top-level import (or after the shebang if there are none). Use `multiprocessing.Pool.apply_async` with a fixed pool of 8 workers for parallelism, `pathlib` for all path handling, `loguru` for logging, complete strict type annotations, and docstrings on all public functions and classes. Accept optional file paths as CLI arguments; otherwise discover `.py` files under the current working directory via `dh.get_files`.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from dh import get_files
from loguru import logger

DH_SRC_DIR: Path = Path("~/projects/py/dh/src/dh").expanduser()
MAX_WORKERS: int = 8


def build_dh_mapping(dh_path: Path) -> dict[str, Path]:
    """Build a mapping from exported symbol name to the source file that defines it.

    Reads ``dh_path/__init__.py`` and inspects relative ``from .module import name``
    statements (``level == 1``) to associate each imported name with
    ``dh_path/module.py``.

    Args:
        dh_path: Directory containing the ``dh`` package's ``__init__.py``.

    Returns:
        A dictionary mapping symbol names to their defining ``.py`` file paths.

    Raises:
        FileNotFoundError: If ``__init__.py`` does not exist under ``dh_path``.
    """
    init_file: Path = dh_path / "__init__.py"
    if not init_file.exists():
        raise FileNotFoundError(f"Could not find __init__.py at {init_file}")
    mapping: dict[str, Path] = {}
    tree: ast.Module = ast.parse(init_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            module_name: str | None = node.module
            if module_name is None:
                continue
            module_path: Path = dh_path / f"{module_name}.py"
            for alias in node.names:
                mapping[alias.name] = module_path
    return mapping


class ModuleDependencyAnalyzer(ast.NodeVisitor):
    """AST visitor that records loaded global names and non-``dh`` imports."""

    def __init__(self, global_names: Iterable[str]) -> None:
        """Initialize the analyzer.

        Args:
            global_names: Names of top-level symbols in the module being analyzed.
        """
        self.global_names: set[str] = set(global_names)
        self.references: set[str] = set()
        self.imported_modules: list[ast.stmt] = []

    def visit_Import(self, node: ast.Import) -> None:
        """Record a plain ``import`` statement."""
        self.imported_modules.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record a non-``dh`` absolute ``from ... import ...`` statement."""
        if node.module != "dh" and node.level == 0:
            self.imported_modules.append(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Record loads of names that match known global symbols."""
        if isinstance(node.ctx, ast.Load) and node.id in self.global_names:
            self.references.add(node.id)


def get_all_dependencies(path: Path, target_symbol: str) -> tuple[set[str], list[str]]:
    """Collect imports and source blocks needed to inline a symbol.

    Recursively resolves intra-file dependencies starting from ``target_symbol``,
    gathers the non-``dh`` imports required by the resolved code, and returns the
    import statement strings together with the source blocks of each needed
    top-level symbol in source order.

    Args:
        path: Path to the module that defines ``target_symbol``.
        target_symbol: Name of the top-level symbol to resolve.

    Returns:
        A tuple ``(needed_imports, source_blocks)`` where ``needed_imports`` is a
        set of import statement strings and ``source_blocks`` is a list of source
        code blocks in definition order.
    """
    if not path.exists():
        return (set(), [])
    content: str = path.read_text(encoding="utf-8")
    tree: ast.Module = ast.parse(content)
    lines: list[str] = content.splitlines()
    nodes_by_name: dict[str, ast.stmt] = {}
    global_imports: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes_by_name[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes_by_name[target.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module_attr: str = getattr(node, "module", "") or ""
            level_attr: int = getattr(node, "level", 0) or 0
            if module_attr != "dh" and level_attr == 0:
                global_imports.append(node)
    if target_symbol not in nodes_by_name:
        return (set(), [])
    needed_symbols: set[str] = set()
    to_resolve: list[str] = [target_symbol]
    while to_resolve:
        current: str = to_resolve.pop(0)
        if current in needed_symbols:
            continue
        needed_symbols.add(current)
        node = nodes_by_name.get(current)
        if node:
            analyzer: ModuleDependencyAnalyzer = ModuleDependencyAnalyzer(
                nodes_by_name.keys()
            )
            analyzer.visit(node)
            for ref in analyzer.references:
                if ref not in needed_symbols:
                    to_resolve.append(ref)
    needed_imports: set[str] = set()
    all_code_text: str = "\n".join(
        "\n".join(lines[nodes_by_name[sym].lineno - 1 : nodes_by_name[sym].end_lineno])
        for sym in needed_symbols
        if nodes_by_name[sym].end_lineno is not None
    )
    for imp in global_imports:
        imp_text: str = ast.unparse(imp)
        if isinstance(imp, (ast.Import, ast.ImportFrom)):
            for alias in imp.names:
                name: str = alias.asname or alias.name
                if name in all_code_text:
                    needed_imports.add(imp_text)
    source_blocks: list[str] = []
    sorted_symbols: list[str] = sorted(
        needed_symbols, key=lambda s: nodes_by_name[s].lineno
    )
    for sym in sorted_symbols:
        node = nodes_by_name[sym]
        end_lineno: int = (
            node.end_lineno if node.end_lineno is not None else node.lineno
        )
        source_blocks.append("\n".join(lines[node.lineno - 1 : end_lineno]))
    return (needed_imports, source_blocks)


def process_file(path: Path, mapping: dict[str, Path]) -> None:
    """Inline ``dh`` imports in a single Python file.

    Skips this script itself, files that do not reference ``dh``, and files
    without any ``dh`` import statements. Otherwise rewrites the file in place,
    replacing ``dh`` imports with the resolved dependency imports and source
    blocks.

    Args:
        path: Path to the Python file to refactor.
        mapping: Mapping from ``dh`` symbol names to their defining files.
    """
    path = Path(path)
    if path.resolve() == Path(__file__).resolve():
        return
    try:
        content: str = path.read_text(encoding="utf-8")
        if "dh" not in content:
            return
        tree: ast.Module = ast.parse(content)
        lines: list[str] = content.splitlines(keepends=True)
        dh_import_ranges: list[tuple[int, int]] = []
        used_dh_symbols: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "dh":
                dh_import_ranges.append((node.lineno - 1, node.end_lineno))
                for alias in node.names:
                    used_dh_symbols.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "dh":
                        dh_import_ranges.append((node.lineno - 1, node.end_lineno))
        if not used_dh_symbols:
            return
        for start, end in sorted(dh_import_ranges, reverse=True):
            del lines[start:end]
        file_imports: set[str] = set()
        file_source_blocks: list[str] = []
        for symbol in used_dh_symbols:
            if symbol in mapping:
                imports, blocks = get_all_dependencies(mapping[symbol], symbol)
                file_imports.update(imports)
                for block in blocks:
                    if block not in file_source_blocks:
                        file_source_blocks.append(block)
            else:
                file_source_blocks.append(
                    f"# WARNING: Source code for '{symbol}' not found."
                )
        if file_source_blocks:
            injection_parts: list[str] = []
            if file_imports:
                injection_parts.append("\n".join(file_imports))
            injection_parts.extend(file_source_blocks)
            inlined_code: str = "\n\n" + "\n\n".join(injection_parts) + "\n\n"
            insert_idx: int = 0
            if lines and lines[0].startswith("#!"):
                insert_idx = 1
            tree = ast.parse(content)
            last_import_end: int = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module == "dh":
                        continue
                    if isinstance(node, ast.Import):
                        skip: bool = False
                        for alias in node.names:
                            if alias.name == "dh":
                                skip = True
                                break
                        if skip:
                            continue
                    last_import_end = max(last_import_end, node.end_lineno)
                else:
                    break
            if last_import_end > 0:
                insert_idx = last_import_end
            if insert_idx > 0 and lines[insert_idx - 1].strip():
                inlined_code = "\n" + inlined_code
            new_content: str = (
                "".join(lines[:insert_idx]) + inlined_code + "".join(lines[insert_idx:])
            )
            path.write_text(new_content, encoding="utf-8")
            print("Refactored: {} -> Inlined: {}", path, ", ".join(used_dh_symbols))
    except Exception as e:
        logger.exception("Error processing {}: {}", path, e)


def main() -> int:
    """Entry point: build the mapping and refactor files in parallel.

    Returns:
        Exit code (0 on success, 1 if the ``dh`` mapping cannot be built).
    """
    try:
        mapping: dict[str, Path] = build_dh_mapping(DH_SRC_DIR)
    except FileNotFoundError as e:
        logger.error("Error: {}", e)
        return 1
    cwd: Path = Path.cwd()
    args: list[str] = sys.argv[1:]
    py_files: list[Path] = (
        [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    )
    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_file, (p, mapping)) for p in py_files
        ]
        for ar in async_results:
            ar.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
