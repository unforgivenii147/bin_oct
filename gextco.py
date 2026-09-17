#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path

from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class Entity:
    name: str
    path: str
    line_number: int


@dataclass
class ExtractionResult:
    path: Path
    classes: list[Entity]
    functions: list[Entity]
    constants: list[Entity]
    imports: set[str]


class EntityExtractor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.classes: list[Entity] = []
        self.functions: list[Entity] = []
        self.constants: list[Entity] = []
        self.imports: set[str] = set()
        self._in_class = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(
            Entity(name=node.name, path=str(self.path), line_number=node.lineno)
        )
        old_in_class = self._in_class
        self._in_class = True
        self.generic_visit(node)
        self._in_class = old_in_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self._in_class:
            self.functions.append(
                Entity(
                    name=node.name,
                    path=str(self.path),
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if not self._in_class:
            self.functions.append(
                Entity(
                    name=node.name,
                    path=str(self.path),
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._in_class:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    self.constants.append(
                        Entity(
                            name=target.id,
                            path=str(self.path),
                            line_number=node.lineno,
                        )
                    )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(f"import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.add(f"from {module} import {alias.name}")
        self.generic_visit(node)


def extract_from_file(path: Path) -> ExtractionResult:
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        extractor = EntityExtractor(path)
        extractor.visit(tree)
        return ExtractionResult(
            path=path,
            classes=extractor.classes,
            functions=extractor.functions,
            constants=extractor.constants,
            imports=extractor.imports,
        )
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to parse {path}: {e}")
        return ExtractionResult(
            path=path, classes=[], functions=[], constants=[], imports=set()
        )


def find_python_files(root_dir: Path) -> list[Path]:
    return list(root_dir.rglob("*.py"))


def save_entities(
    output_dir: Path,
    entity_type: str,
    entities_by_file: dict[str, list[Entity]],
    unique_entities: set[str],
) -> None:
    entity_dir = output_dir / entity_type
    entity_dir.mkdir(parents=True, exist_ok=True)
    for path, entities in entities_by_file.items():
        if entities:
            file_name = Path(path).stem + ".txt"
            output_file = entity_dir / file_name
            with open(output_file, "w", encoding="utf-8") as f:
                f.writelines(
                    f"{entity.name} (line {entity.line_number})\n"
                    for entity in sorted(entities, key=lambda e: e.name)
                )
    unique_file = entity_dir / "unique.txt"
    with open(unique_file, "w", encoding="utf-8") as f:
        f.writelines(f"{name}\n" for name in sorted(unique_entities))
    print(f"Saved {len(unique_entities)} unique {entity_type}")


def save_imports(output_dir: Path, imports_by_dir: dict[str, set[str]]) -> None:
    imports_dir = output_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    for dir_name, imports in imports_by_dir.items():
        if imports:
            file_name = f"imports-{dir_name}.txt"
            output_file = imports_dir / file_name
            with open(output_file, "w", encoding="utf-8") as f:
                f.writelines(f"{imp}\n" for imp in sorted(imports))
    print(f"Saved imports for {len(imports_by_dir)} directories")


def main(
    root_dir: str = ".", output_dir: str = "output", num_workers: int | None = None
) -> None:
    root_path = Path(root_dir)
    output_path = Path(output_dir)
    if not root_path.exists():
        logger.error(f"Root directory not found: {root_path}")
        sys.exit(1)
    print(f"Scanning for Python files in {root_path}...")
    py_files = find_python_files(root_path)
    if not py_files:
        logger.warning("No Python files found.")
        return
    print(f"Found {len(py_files)} Python files")
    num_workers = num_workers or cpu_count()
    print(f"Using {num_workers} workers for parallel processing")
    entities_by_file = defaultdict(list)
    unique_classes = set()
    unique_functions = set()
    unique_constants = set()
    imports_by_dir = defaultdict(set)
    with Pool(num_workers) as pool:
        results = list(
            tqdm(
                pool.imap_unordered(extract_from_file, py_files),
                total=len(py_files),
                desc="Extracting entities",
                unit="file",
            )
        )
    print("Aggregating results...")
    for result in results:
        for entity in result.classes:
            entities_by_file["classes"][result.path].append(entity)
            unique_classes.add(entity.name)
        for entity in result.functions:
            entities_by_file["functions"][result.path].append(entity)
            unique_functions.add(entity.name)
        for entity in result.constants:
            entities_by_file["constants"][result.path].append(entity)
            unique_constants.add(entity.name)
        dir_name = result.path.parent.name or "root"
        imports_by_dir[dir_name].update(result.imports)
    entities_by_file = {key: dict(val) for key, val in entities_by_file.items()}
    print(f"Saving results to {output_path}...")
    output_path.mkdir(parents=True, exist_ok=True)
    save_entities(
        output_path, "class", entities_by_file.get("classes", {}), unique_classes
    )
    save_entities(
        output_path, "func", entities_by_file.get("functions", {}), unique_functions
    )
    save_entities(
        output_path, "const", entities_by_file.get("constants", {}), unique_constants
    )
    save_imports(output_path, imports_by_dir)
    print("=" * 40)
    print("Extraction Summary:")
    print(f"  Files processed: {len(py_files)}")
    print(f"  Unique classes: {len(unique_classes)}")
    print(f"  Unique functions: {len(unique_functions)}")
    print(f"  Unique constants: {len(unique_constants)}")
    print(f"  Total imports: {sum(len(v) for v in imports_by_dir.values())}")
    print("=" * 40)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract entities from Python files recursively"
    )
    parser.add_argument(
        "-r",
        "--root",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o", "--output", default="output", help="Output directory (default: output)"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        help="Number of parallel workers (default: CPU count)",
    )
    args = parser.parse_args()
    main(args.root, args.output, args.workers)
