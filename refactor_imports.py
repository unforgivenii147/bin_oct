#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a ``repeated.json`` manifest of duplicated top-level functions, classes,
and constant assignments across every ``.py`` file under the current directory,
then use that manifest to refactor each affected file: strip the named
definitions and inject a single ``from dh import ...`` line so the shared
versions come from ``dh`` instead. Analysis and refactoring both run on a fixed
multiprocessing.Pool of 8 workers; logging via loguru.
"""

import ast
import collections
import json
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Final, cast

import astor  # type: ignore[import-untyped]
from loguru import logger

REPEATED_JSON_PATH: Final[Path] = Path("repeated.json")
MAX_WORKERS: Final[int] = 8
DUPLICATE_THRESHOLD: Final[int] = 2

DefinitionKey = tuple[str, str, str]
DefinitionsMap = collections.defaultdict[DefinitionKey, list[str]]
SourceMap = dict[DefinitionKey, str | None]
FileMap = dict[str, list[str]]
Task = tuple[Path, list[str]]


def get_source(node: ast.AST, content: str) -> str | None:
    """
    Return the source segment that produced ``node``.

    Args:
        node: The AST node whose source text is desired.
        content: The full source text ``node`` came from.

    Returns:
        The source segment, or ``None`` if it cannot be recovered.
    """
    return ast.get_source_segment(content, node)


def normalize_source(source: str | None) -> str:
    """
    Normalize source text for duplicate comparison by stripping trailing
    whitespace on each line and trimming surrounding whitespace.

    Args:
        source: Source text, possibly ``None``.

    Returns:
        The normalized source (empty string when ``source`` is ``None``).
    """
    if not source:
        return ""
    return "\n".join(line.rstrip() for line in source.strip().splitlines())


def _iter_target_py_files(root: Path) -> list[Path]:
    """
    Collect all ``.py`` files under ``root``, skipping ``.git`` directories.

    Args:
        root: Directory to walk.

    Returns:
        A list of Python file paths.
    """
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        files.append(path)
    return files


def _collect_definitions(
    file_path: Path,
    definitions: DefinitionsMap,
    source_map: SourceMap,
) -> None:
    """
    Record every top-level function/class/constant definition in ``file_path``.

    Keys are ``(kind, name, normalized_source)``; values are the list of files
    that contain the definition. Parse errors are silently ignored so a single
    broken file cannot abort the scan.

    Args:
        file_path: Python source file to inspect.
        definitions: Accumulator for definition -> file list.
        source_map: Accumulator for definition -> original source snippet.
    """
    try:
        content: str = file_path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(content)
    except Exception:
        return

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            source: str | None = get_source(node, content)
            norm: str = normalize_source(source)
            key: DefinitionKey = (type(node).__name__, node.name, norm)
            definitions[key].append(str(file_path))
            if key not in source_map:
                source_map[key] = source
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    source = get_source(node, content)
                    norm = normalize_source(source)
                    key = ("Constant", target.id, norm)
                    definitions[key].append(str(file_path))
                    if key not in source_map:
                        source_map[key] = source


def analyze_files() -> list[dict[str, Any]]:
    """
    Scan every ``.py`` file under the current directory for duplicated
    top-level definitions.

    A definition is "repeated" when it appears in more than
    :data:`DUPLICATE_THRESHOLD` distinct files. The returned list is unsorted;
    the caller is expected to sort by ``count`` if desired.

    Returns:
        A list of dicts with keys ``type``, ``name``, ``source``, ``count``,
        and ``files``.
    """
    cwd: Path = Path.cwd()
    definitions: DefinitionsMap = collections.defaultdict(list)
    source_map: SourceMap = {}

    for py_file in _iter_target_py_files(cwd):
        _collect_definitions(py_file, definitions, source_map)

    repeated: list[dict[str, Any]] = []
    for key, paths in definitions.items():
        unique_paths: list[str] = list(set(paths))
        if len(unique_paths) > DUPLICATE_THRESHOLD:
            repeated.append(
                {
                    "type": key[0],
                    "name": key[1],
                    "source": source_map[key],
                    "count": len(unique_paths),
                    "files": unique_paths,
                }
            )

    return repeated


def write_repeated_json(repeated: list[dict[str, Any]]) -> None:
    """
    Persist the analysis result to :data:`REPEATED_JSON_PATH`, sorted by
    descending duplicate count.

    Args:
        repeated: Output of :func:`analyze_files`.
    """
    repeated.sort(key=lambda item: item["count"], reverse=True)
    REPEATED_JSON_PATH.write_text(
        json.dumps(repeated, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {len(repeated)} entries to {REPEATED_JSON_PATH}")


def load_refactoring_maps() -> FileMap:
    """
    Load :data:`REPEATED_JSON_PATH` and invert it into a basename -> object
    names map.

    Returns:
        A mapping from Python file basename to the list of top-level object
        names that should be stripped from that file.
    """
    with REPEATED_JSON_PATH.open("r", encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)

    file_to_objects: collections.defaultdict[str, list[str]] = collections.defaultdict(
        list
    )
    for item in data:
        obj_name: str = item["name"]
        for file_path_str in item["files"]:
            p: Path = Path(file_path_str)
            file_to_objects[p.name].append(obj_name)

    return dict(file_to_objects)


class ASTStripper(ast.NodeTransformer):
    """
    AST transformer that removes top-level functions, classes, and assignments
    whose names appear in :attr:`target_names`.

    Attributes:
        target_names: Names to strip.
        removed_something: Set to ``True`` once any node is removed.
    """

    def __init__(self, target_names: list[str]) -> None:
        """
        Initialize the stripper.

        Args:
            target_names: Names of objects to remove from the tree.
        """
        super().__init__()
        self.target_names: set[str] = set(target_names)
        self.removed_something: bool = False

    def visit_FunctionDef(  # type: ignore[override]
        self, node: ast.FunctionDef
    ) -> ast.FunctionDef | None:
        """Remove the function if its name is targeted; otherwise recurse."""
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.FunctionDef, self.generic_visit(node))

    def visit_AsyncFunctionDef(  # type: ignore[override]
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef | None:
        """Remove the async function if its name is targeted; otherwise recurse."""
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.AsyncFunctionDef, self.generic_visit(node))

    def visit_ClassDef(  # type: ignore[override]
        self, node: ast.ClassDef
    ) -> ast.ClassDef | None:
        """Remove the class if its name is targeted; otherwise recurse."""
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.ClassDef, self.generic_visit(node))

    def visit_Assign(  # type: ignore[override]
        self, node: ast.Assign
    ) -> ast.Assign | None:
        """Remove the assignment if any target name matches; otherwise recurse."""
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in self.target_names:
                self.removed_something = True
                return None
        return cast(ast.Assign, self.generic_visit(node))


def refactor_single_file(file_path: Path, objects_to_remove: list[str]) -> bool:
    """
    Strip the named objects from ``file_path`` and prepend a ``dh`` import.

    Inserts the ``from dh import ...`` line after any shebang and after a
    module docstring.

    Args:
        file_path: Python source file to refactor in place.
        objects_to_remove: Names to delete and re-import from ``dh``.

    Returns:
        ``True`` if the file was modified, otherwise ``False``.
    """
    try:
        source_code: str = file_path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(source_code)
    except Exception as exc:
        logger.error(f"❌ Error parsing {file_path.name}: {exc}")
        return False

    stripper: ASTStripper = ASTStripper(objects_to_remove)
    modified_tree: ast.AST = stripper.visit(tree)
    ast.fix_missing_locations(modified_tree)

    if not stripper.removed_something:
        print(f"➖ No matching structural nodes found inside {file_path.name}")
        return False

    import_names: str = ", ".join(sorted(objects_to_remove))
    import_statement: str = f"from dh import {import_names}\n"

    try:
        cleaned_source: str = astor.to_source(modified_tree)
    except Exception as exc:
        logger.error(f"❌ Failed to stringify AST for {file_path.name}: {exc}")
        return False

    lines: list[str] = cleaned_source.splitlines(keepends=True)
    insert_idx: int = 0
    if lines and lines[0].startswith("#!"):
        insert_idx = 1
    if len(lines) > insert_idx and (
        lines[insert_idx].strip().startswith('"""')
        or lines[insert_idx].strip().startswith("'''")
    ):
        insert_idx += 1

    lines.insert(insert_idx, import_statement)

    try:
        file_path.write_text("".join(lines), encoding="utf-8")
        print(
            f"✅ Refactored {file_path.name}: Stripped {objects_to_remove} "
            f"-> added 'dh' import"
        )
        return True
    except Exception as exc:
        logger.error(f"❌ Error writing updates back to {file_path.name}: {exc}")
        return False


def main() -> None:
    """
    Analyze the project for duplicated definitions, write ``repeated.json``,
    then refactor every local file listed in it in parallel.
    """
    print("🔎 Analyzing Python files for duplicated definitions...")
    repeated: list[dict[str, Any]] = analyze_files()

    if not repeated:
        logger.warning(
            "No definitions duplicated in more than "
            f"{DUPLICATE_THRESHOLD} files. Nothing to refactor."
        )
        return

    write_repeated_json(repeated)

    refactor_map: FileMap = load_refactoring_maps()
    current_dir: Path = Path(".")
    local_files: dict[str, Path] = {f.name: f for f in current_dir.glob("*.py")}

    tasks: list[Task] = [
        (local_files[filename], objects)
        for filename, objects in refactor_map.items()
        if filename in local_files
    ]

    if not tasks:
        print("No matching files found in the current directory to refactor.")
        return

    print(
        f"🚀 Found {len(tasks)} files to clean structural code from. "
        f"Starting parallel processing..."
    )

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[bool]] = [
            pool.apply_async(refactor_single_file, (file_path, objects))
            for file_path, objects in tasks
        ]
        for async_res in async_results:
            try:
                async_res.get()
            except Exception as exc:
                logger.error(f"❌ Worker raised: {exc}")

    print("🎉 Structural refactoring complete! All duplicate bodies stripped.")


if __name__ == "__main__":
    raise SystemExit(main())
