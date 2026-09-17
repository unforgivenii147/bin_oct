#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a script that detects duplicate Python functions across a codebase and optionally refactors them into a shared module.

The script scans directories for Python files, parses them with ast, groups
FunctionDef nodes by (name, normalized source), reports duplicates that appear
in two or more files, writes the shared function sources to repeated_functions.py,
and can apply a refactor that removes duplicate definitions and adds
`from dh import ...` imports. It uses multiprocessing.Pool.apply_async with a
fixed pool of 8 workers, pathlib for all path handling, loguru for logging, and
complete type annotations.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any

# Module-level constants
POOL_SIZE: int = 8
DEFAULT_OUTPUT_NAME: str = "repeated_functions.py"
IMPORT_MODULE_NAME: str = "dh"
DefinitionKey = tuple[str, str]
DefinitionMap = dict[DefinitionKey, list[str]]
SourceMap = dict[DefinitionKey, str]
RepeatedItem = dict[str, Any]


def get_source(node: ast.AST, content: str) -> str:
    """Return the source segment for *node* from *content*, or an empty string."""
    return ast.get_source_segment(content, node) or ""


def normalize_source(source: str) -> str:
    """Return *source* stripped of surrounding whitespace and trailing spaces per line."""
    if not source:
        return ""
    return "\n".join(line.rstrip() for line in source.strip().splitlines())


def analyze_file(path: Path) -> dict[str, Any]:
    """Analyze a single Python file for top-level function definitions.

    Returns a dict with ``definitions`` mapping (name, normalized source) to a
    list of file paths, and ``source_map`` mapping the same key to the original
    source text.
    """
    definitions: defaultdict[DefinitionKey, list[str]] = defaultdict(list)
    source_map: SourceMap = {}
    try:
        content: str = path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                source: str = get_source(node, content)
                norm: str = normalize_source(source)
                key: DefinitionKey = (node.name, norm)
                definitions[key].append(str(path))
                if key not in source_map:
                    source_map[key] = source
    except Exception:
        pass
    return {"definitions": dict(definitions), "source_map": dict(source_map)}


def analyze_files(target_dirs: list[Path] | None = None) -> list[RepeatedItem]:
    """Find duplicate top-level functions across all Python files in *target_dirs*.

    Returns a list of dicts sorted by descending duplicate count, each containing
    ``name``, ``source``, ``count``, and ``files``.
    """
    resolved_dirs: list[Path] = target_dirs if target_dirs else [Path.cwd()]
    py_files: list[Path] = []
    for target_dir in resolved_dirs:
        py_files.extend(target_dir.rglob("*.py"))
    py_files = [f for f in py_files if ".git" not in f.parts]

    definitions: defaultdict[DefinitionKey, list[str]] = defaultdict(list)
    source_map: SourceMap = {}

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [pool.apply_async(analyze_file, (f,)) for f in py_files]
        results: list[dict[str, Any]] = [r.get() for r in async_results]

    for result in results:
        result_defs: DefinitionMap = result["definitions"]
        result_sources: SourceMap = result["source_map"]
        for key, paths in result_defs.items():
            definitions[key].extend(paths)
        source_map.update(result_sources)

    repeated: list[RepeatedItem] = []
    for key, paths in definitions.items():
        unique_paths: list[str] = list(set(paths))
        if len(unique_paths) >= 2:
            repeated.append(
                {
                    "name": key[0],
                    "source": source_map.get(key, ""),
                    "count": len(unique_paths),
                    "files": unique_paths,
                }
            )
    repeated.sort(key=lambda x: x["count"], reverse=True)
    return repeated


def save_dh_module(
    repeated: list[RepeatedItem],
    output_path: Path = Path(DEFAULT_OUTPUT_NAME),
) -> None:
    """Write the source of all repeated functions to *output_path*."""
    lines: list[str] = []
    for item in repeated:
        source: str = item["source"]
        lines.append(source)
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def refactor_file(path: Path, repeated: list[RepeatedItem]) -> None:
    """Remove duplicated functions from *path* and add imports for them."""
    try:
        content: str = path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(content)
    except Exception:
        return

    imports_to_add: set[str] = set()
    lines: list[str] = content.splitlines(keepends=True)
    nodes_to_remove: list[ast.FunctionDef] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for item in repeated:
                if node.name == item["name"]:
                    source: str = get_source(node, content)
                    if normalize_source(source) == normalize_source(item["source"]):
                        imports_to_add.add(item["name"])
                        nodes_to_remove.append(node)

    if not imports_to_add:
        return

    lines_to_keep: list[str] = []
    for i, line in enumerate(lines):
        skip: bool = False
        for node in nodes_to_remove:
            if (
                node.lineno is not None
                and node.end_lineno is not None
                and node.lineno - 1 <= i < node.end_lineno
            ):
                skip = True
                break
        if not skip:
            lines_to_keep.append(line)

    import_stmt: str = (
        f"from {IMPORT_MODULE_NAME} import " + ", ".join(sorted(imports_to_add)) + "\n"
    )
    insert_pos: int = 0
    for i, line in enumerate(lines_to_keep):
        if line.strip() and not line.strip().startswith("#"):
            insert_pos = i
            break
    lines_to_keep.insert(insert_pos, import_stmt)
    path.write_text("".join(lines_to_keep), encoding="utf-8")


def apply_refactoring(
    repeated: list[RepeatedItem],
    target_dirs: list[Path] | None = None,
) -> None:
    """Apply refactoring to every Python file under *target_dirs* using a pool."""
    resolved_dirs: list[Path] = target_dirs if target_dirs else [Path.cwd()]
    py_files: list[Path] = []
    for target_dir in resolved_dirs:
        py_files.extend(target_dir.rglob("*.py"))
    py_files = [
        f for f in py_files if ".git" not in f.parts and f.name != DEFAULT_OUTPUT_NAME
    ]

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(refactor_file, (f, repeated)) for f in py_files
        ]
        for r in async_results:
            r.get()


def main() -> None:
    """Parse command-line arguments and run duplicate detection/refactoring."""
    parser = argparse.ArgumentParser(
        description="Detect and refactor duplicate functions"
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply refactoring: remove duplicates and add imports",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Directories or files to process (default: current directory)",
    )
    args = parser.parse_args()

    target_dirs: list[Path] | None = (
        [Path(p) for p in args.paths] if args.paths else None
    )
    repeated: list[RepeatedItem] = analyze_files(target_dirs)
    save_dh_module(repeated)

    if args.apply:
        apply_refactoring(repeated, target_dirs)
        print(f"Saved {len(repeated)} functions to {DEFAULT_OUTPUT_NAME}")
    else:
        print(
            f"Found {len(repeated)} repeated functions. Saved to {DEFAULT_OUTPUT_NAME}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
