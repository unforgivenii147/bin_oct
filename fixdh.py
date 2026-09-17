#!/data/data/com.termux/files/home/.local/bin/python
"""Refactor a Python script that inlines code from a local `dh` package.

Generate a script that:
- Locates the `dh` source tree at `~/projects/py/dh/src/dh`.
- Builds a public-symbol map from `dh/__init__.py` and a symbol-source index
  from every `.py` file in the `dh` tree using `ast`.
- Walks target Python files (given as argv or discovered under cwd) and, for
  each top-level def/class/assign whose source exactly matches an entry in the
  symbol index, removes it and (if public) replaces it with a `from dh import ...`.
- Removes newly-unused top-level imports after deletions.
- Runs work in parallel via `multiprocessing.Pool.apply_async` with 8 workers.
- Logs with `loguru` and uses `pathlib` throughout.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

DH_SRC_DIR: Path = Path("~/projects/py/dh/src/dh").expanduser()
POOL_SIZE: int = 8


def get_files(root: Path, ext: Iterable[str] | None = None) -> list[Path]:
    """Return all files under ``root`` matching any of the given extensions."""
    exts = tuple(ext) if ext is not None else (".py",)
    return [p for p in root.rglob("*") if p.is_file() and p.suffix in exts]


def build_dh_public_mapping(dh_path: Path) -> dict[str, Path]:
    """Map public symbol name -> source module path from ``dh/__init__.py``."""
    init_file = dh_path / "__init__.py"
    if not init_file.exists():
        raise FileNotFoundError(f"Could not find __init__.py at {init_file}")

    mapping: dict[str, Path] = {}
    tree = ast.parse(init_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            module_path = dh_path / f"{node.module}.py"
            for alias in node.names:
                mapping[alias.name] = module_path
    return mapping


def build_dh_symbol_index(dh_path: Path) -> dict[str, set[str]]:
    """Index top-level definitions by name -> set of exact source snippets."""
    index: dict[str, set[str]] = {}
    for py_file in get_files(dh_path, ext=[".py"]):
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        lines = content.splitlines()
        for node in tree.body:
            name: str | None = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.Assign):
                targets = node.targets
                if len(targets) == 1 and isinstance(targets[0], ast.Name):
                    name = targets[0].id
            if name is None or node.end_lineno is None:
                continue
            src = "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
            index.setdefault(name, set()).add(src)
    return index


def is_import_used(node: ast.Import | ast.ImportFrom, text: str) -> bool:
    """Return True if any name bound by ``node`` appears in ``text``."""
    for alias in node.names:
        bound_name = alias.asname or alias.name.split(".")[0]
        if re.search(rf"\b{re.escape(bound_name)}\b", text):
            return True
    return False


def process_file(
    path_str: str,
    public_map: dict[str, Path],
    symbol_index: dict[str, set[str]],
) -> str | None:
    """Process a single file: strip inlined dh symbols and restore imports."""
    path = Path(path_str)
    if path.resolve() == Path(__file__).resolve():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning(f"Skipping {path}: {e}")
        return None

    lines = content.splitlines(keepends=True)
    to_remove_ranges: list[tuple[int, int]] = []
    to_import: set[str] = set()

    for node in tree.body:
        name: str | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            targets = node.targets
            if len(targets) == 1 and isinstance(targets[0], ast.Name):
                name = targets[0].id
        if name is None or name not in symbol_index or node.end_lineno is None:
            continue

        node_src = "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
        if node_src not in symbol_index[name]:
            continue

        to_remove_ranges.append((node.lineno - 1, node.end_lineno))
        if name in public_map:
            to_import.add(name)

    if not to_remove_ranges:
        return None

    for start, end in sorted(to_remove_ranges, reverse=True):
        del lines[start:end]

    remaining_text = "".join(lines)
    try:
        remaining_tree: ast.Module | None = ast.parse(remaining_text)
    except SyntaxError:
        remaining_tree = None

    if remaining_tree is not None:
        import_removal_ranges: list[tuple[int, int]] = []
        for node in remaining_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if node.end_lineno is None:
                    continue
                stmt_text = "".join(lines[node.lineno - 1 : node.end_lineno])
                rest_text = remaining_text.replace(stmt_text, "", 1)
                if not is_import_used(node, rest_text):
                    import_removal_ranges.append((node.lineno - 1, node.end_lineno))
        for start, end in sorted(import_removal_ranges, reverse=True):
            del lines[start:end]

    new_content = "".join(lines)
    if to_import:
        import_line = f"from dh import {', '.join(sorted(to_import))}\n"
        body_lines = new_content.splitlines(keepends=True)
        insert_idx = 1 if body_lines and body_lines[0].startswith("#!") else 0
        body_lines.insert(insert_idx, import_line)
        new_content = "".join(body_lines)

    if new_content == content:
        return None

    path.write_text(new_content, encoding="utf-8")
    label = ", ".join(sorted(to_import)) if to_import else "(internal helpers only)"
    return f"Reverted: {path} -> Restored import: {label}"


def _worker(
    path_str: str,
    public_map: dict[str, Path],
    symbol_index: dict[str, set[str]],
) -> str | None:
    """Multiprocessing entry point: run ``process_file`` and return a log line."""
    return process_file(path_str, public_map, symbol_index)


def main() -> int:
    """Entry point: build indexes and dispatch per-file work to a pool."""
    try:
        public_map = build_dh_public_mapping(DH_SRC_DIR)
    except FileNotFoundError as e:
        logger.error(f"{e}")
        return 1

    symbol_index = build_dh_symbol_index(DH_SRC_DIR)

    cwd = Path.cwd()
    args = sys.argv[1:]
    py_files = [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    path_strs = [str(p) for p in py_files]

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(_worker, (p, public_map, symbol_index)) for p in path_strs
        ]
        for ar in async_results:
            try:
                msg = ar.get()
            except Exception as e:  # noqa: BLE001
                logger.exception(f"Worker failed: {e}")
                continue
            if msg:
                print(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
