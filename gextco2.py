#!/data/data/com.termux/files/home/.local/bin/python
"""Extract Python code entities from files and archives.

This module scans directories for Python files and archives, extracts
code entities (classes, functions, methods, constants) and saves them
as individual files with proper imports. Methods are converted to
standalone functions with 'self' references removed.
"""

import ast
import os
import re
import sys
import tarfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from loguru import logger

try:
    import zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".venv", "node_modules", ".env", ".pytest_cache"}
)
COMMON_IMPORTS: dict[str, set[str]] = {
    "typing": {
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Optional",
        "Union",
        "Any",
        "Callable",
        "Type",
        "Generic",
        "TypeVar",
        "cast",
        "overload",
        "Protocol",
        "Iterator",
        "Iterable",
        "Sequence",
        "Mapping",
    },
    "dataclasses": {
        "dataclass",
        "field",
        "InitVar",
        "FrozenInstanceError",
        "MISSING",
        "fields",
        "asdict",
        "astuple",
        "make_dataclass",
        "replace",
    },
    "functools": {
        "lru_cache",
        "wraps",
        "partial",
        "total_ordering",
        "reduce",
        "cmp_to_key",
        "singledispatch",
    },
    "itertools": {
        "combinations",
        "permutations",
        "product",
        "chain",
        "groupby",
        "repeat",
        "cycle",
        "islice",
        "takewhile",
        "dropwhile",
    },
    "pathlib": {
        "Path",
        "PurePath",
        "PureWindowsPath",
        "PurePosixPath",
        "WindowsPath",
        "PosixPath",
    },
    "datetime": {
        "datetime",
        "date",
        "time",
        "timedelta",
        "timezone",
        "tzinfo",
        "strptime",
        "now",
    },
    "json": {"dumps", "loads", "dump", "load", "JSONEncoder", "JSONDecoder"},
    "re": {
        "compile",
        "match",
        "search",
        "findall",
        "finditer",
        "sub",
        "split",
        "escape",
        "IGNORECASE",
        "MULTILINE",
        "DOTALL",
    },
    "collections": {
        "defaultdict",
        "OrderedDict",
        "Counter",
        "deque",
        "namedtuple",
        "ChainMap",
    },
    "enum": {"Enum", "IntEnum", "Flag", "IntFlag", "auto", "unique"},
    "abc": {
        "ABC",
        "abstractmethod",
        "abstractproperty",
        "ABCMeta",
        "abstractclassmethod",
    },
    "contextlib": {
        "contextmanager",
        "closing",
        "suppress",
        "redirect_stdout",
        "redirect_stderr",
    },
    "copy": {"copy", "deepcopy"},
    "pickle": {"dumps", "loads", "dump", "load"},
    "logging": {
        "getLogger",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "basicConfig",
    },
    "os": {
        "path",
        "environ",
        "getcwd",
        "chdir",
        "listdir",
        "mkdir",
        "makedirs",
        "remove",
        "rmdir",
    },
    "sys": {"argv", "exit", "stdout", "stderr", "stdin", "path", "modules"},
    "subprocess": {"run", "Popen", "PIPE", "STDOUT", "CalledProcessError"},
    "threading": {"Thread", "Lock", "RLock", "Condition", "Semaphore", "Event"},
    "asyncio": {"run", "gather", "create_task", "sleep", "Queue", "Event", "Lock"},
    "urllib": {"request", "parse", "error"},
    "requests": {"get", "post", "put", "delete", "Session", "Response"},
    "numpy": {"array", "zeros", "ones", "arange", "linspace", "ndarray"},
    "pandas": {"DataFrame", "Series", "read_csv", "read_excel", "concat", "merge"},
}


@dataclass
class Entity:
    """Represents a Python code entity (class, function, method, or constant)."""

    name: str
    type: str
    source: str
    full_name: str
    source_file: str
    line_number: int
    imports: set[str] = field(default_factory=set)
    decorators: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Contains extraction results for a single file."""

    path: str
    entities: list[Entity] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)


class CodeValidator:
    """Validates Python code before writing to files."""

    @staticmethod
    def validate_python_code(source: str) -> tuple[bool, str | None]:
        """Validate Python source code.

        Args:
            source: Python source code as string

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Try to parse the code
            tree = ast.parse(source)

            # Check for syntax errors
            compile(source, "<validation>", "exec")

            # Additional validation: check for undefined names (basic check)
            undefined_names = CodeValidator._find_undefined_names(tree)
            if undefined_names:
                # Don't fail on common builtins or typing imports
                builtins = (
                    set(dir(__builtins__))
                    if isinstance(__builtins__, dict)
                    else set(dir(__builtins__))
                )
                common_names = {
                    "self",
                    "cls",
                    "List",
                    "Dict",
                    "Set",
                    "Tuple",
                    "Optional",
                    "Union",
                    "Any",
                    "Callable",
                    "Type",
                    "Generic",
                    "TypeVar",
                    "Path",
                    "datetime",
                    "date",
                    "time",
                    "timedelta",
                    "timezone",
                    "json",
                    "re",
                    "os",
                    "sys",
                    "logging",
                    "logger",
                    "loguru",
                }
                truly_undefined = undefined_names - builtins - common_names
                if truly_undefined:
                    # This is not a hard error, just a warning
                    logger.debug(f"Potential undefined names: {truly_undefined}")

            return (True, None)
        except SyntaxError as e:
            return (False, f"Syntax error: {e}")
        except Exception as e:
            return (False, f"Validation error: {e}")

    @staticmethod
    def _find_undefined_names(tree: ast.AST) -> set[str]:
        """Find potentially undefined names in AST.

        Args:
            tree: AST tree to analyze

        Returns:
            Set of potentially undefined names
        """
        undefined = set()
        defined = set()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    undefined.add(node.id)
                elif isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    defined.add(name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name != "*":
                        defined.add(name)

        return undefined - defined


class MethodConverter:
    """Converts class methods to standalone functions."""

    @staticmethod
    def method_to_function(source: str) -> str:
        """Convert a method to a standalone function by removing 'self'.

        Args:
            source: Method source code

        Returns:
            Function source code with 'self' removed
        """
        try:
            tree = ast.parse(source)

            # Find the function definition
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Remove 'self' from arguments
                    if node.args.args and node.args.args[0].arg == "self":
                        node.args.args.pop(0)
                        # Also remove self from posonlyargs if present
                        if (
                            node.args.posonlyargs
                            and node.args.posonlyargs[0].arg == "self"
                        ):
                            node.args.posonlyargs.pop(0)

                    # Remove 'self.' from attribute access
                    MethodConverter._remove_self_references(node)

                    # Remove decorators that are class-specific
                    node.decorator_list = [
                        d
                        for d in node.decorator_list
                        if not MethodConverter._is_class_decorator(d)
                    ]

                    # Convert to source
                    return ast.unparse(node)

            return source
        except Exception as e:
            logger.warning(f"Failed to convert method to function: {e}")
            return source

    @staticmethod
    def _remove_self_references(node: ast.AST) -> None:
        """Remove 'self.' references from attribute access.

        Args:
            node: AST node to process
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name) and child.value.id == "self":
                    # Replace self.attr with just attr
                    child.value = ast.Name(id=child.attr, ctx=ast.Load())
                    child.attr = ""
            elif isinstance(child, ast.Name) and child.id == "self":
                child.id = "self_removed"  # This should not remain in final code

    @staticmethod
    def _is_class_decorator(decorator: ast.expr) -> bool:
        """Check if a decorator is class-specific.

        Args:
            decorator: Decorator AST node

        Returns:
            True if the decorator is class-specific
        """
        if isinstance(decorator, ast.Name):
            return decorator.id in {
                "staticmethod",
                "classmethod",
                "property",
                "abstractmethod",
            }
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr in {
                "staticmethod",
                "classmethod",
                "property",
                "abstractmethod",
            }
        return False


class ImportAnalyzer:
    """Analyzes and manages Python imports."""

    @staticmethod
    def extract_imports_from_source(source: str) -> set[str]:
        """Extract import statements from source code.

        Args:
            source: Python source code as string

        Returns:
            Set of import statements found in the source
        """
        imports: set[str] = set()
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = ", ".join(alias.name for alias in node.names)
                    if node.level > 0:
                        module = "." * node.level + module
                    imports.add(f"from {module} import {names}")
        except SyntaxError:
            pass
        return imports

    @staticmethod
    def detect_needed_imports(source: str) -> set[str]:
        """Detect imports needed based on symbols used in the code.

        Args:
            source: Python source code as string

        Returns:
            Set of import statements that might be needed
        """
        needed: set[str] = set()
        for module, symbols in COMMON_IMPORTS.items():
            for symbol in symbols:
                if re.search(f"\\b{re.escape(symbol)}\\b", source):
                    if module == "typing":
                        needed.add(f"from typing import {symbol}")
                    elif module == "dataclasses":
                        needed.add(f"from dataclasses import {symbol}")
                    elif module == "abc":
                        needed.add(f"from abc import {symbol}")
                    elif module == "functools":
                        needed.add(f"from functools import {symbol}")
                    elif module == "enum":
                        needed.add(f"from enum import {symbol}")
                    else:
                        needed.add(f"from {module} import {symbol}")
        if "Path(" in source or "PurePath(" in source:
            needed.add("from pathlib import Path")
        if "datetime(" in source or "date(" in source:
            needed.add("from datetime import datetime, date")
        if "logging.getLogger" in source or "logger =" in source:
            needed.add("import logging")
        return needed

    @staticmethod
    def consolidate_imports(existing: set[str], needed: set[str]) -> list[str]:
        """Organize and deduplicate imports.

        Args:
            existing: Already existing imports
            needed: Needed imports to add

        Returns:
            List of organized import statements
        """
        all_imports = existing | needed
        organized: list[str] = []
        stdlib_imports: list[str] = []
        thirdparty_imports: list[str] = []
        local_imports: list[str] = []

        for imp in sorted(all_imports):
            if imp.startswith(("from .", "import .")):
                local_imports.append(imp)
            elif imp.startswith(("from typing", "import typing")):
                stdlib_imports.insert(0, imp)
            elif any(
                imp.startswith((f"from {mod}", f"import {mod}"))
                for mod in [
                    "os",
                    "sys",
                    "json",
                    "re",
                    "pathlib",
                    "datetime",
                    "asyncio",
                    "subprocess",
                    "threading",
                    "logging",
                ]
            ):
                stdlib_imports.append(imp)
            else:
                thirdparty_imports.append(imp)

        organized.extend(sorted(stdlib_imports))
        if thirdparty_imports:
            organized.extend([""] + sorted(thirdparty_imports))
        if local_imports:
            organized.extend([""] + sorted(local_imports))
        return [imp for imp in organized if imp]


class EntityVisitor(ast.NodeVisitor):
    """Visits AST nodes to extract code entities."""

    def __init__(self, source_lines: list[str], path: str):
        """Initialize the entity visitor.

        Args:
            source_lines: Source code split into lines
            path: Path to the source file
        """
        self.source_lines = source_lines
        self.path = path
        self.entities: list[Entity] = []
        self.current_class: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Process regular function definitions."""
        self._process_function(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Process async function definitions."""
        self._process_function(node, is_async=True)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Process class definitions."""
        source = self._get_source_slice(node)
        self.entities.append(
            Entity(
                name=node.name,
                type="class",
                source=source,
                full_name=node.name,
                source_file=self.path,
                line_number=node.lineno,
                decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            )
        )
        old_class = self.current_class
        self.current_class = node.name
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function(
                    item, is_async=isinstance(item, ast.AsyncFunctionDef), in_class=True
                )
            self.visit(item)
        self.current_class = old_class

    def visit_Assign(self, node: ast.Assign) -> None:
        """Process assignment statements."""
        if self.current_class is None:
            for target in node.targets:
                if isinstance(target, ast.Name) and self._is_constant_name(target.id):
                    source = self._get_source_slice(node)
                    self.entities.append(
                        Entity(
                            name=target.id,
                            type="constant",
                            source=source,
                            full_name=target.id,
                            source_file=self.path,
                            line_number=node.lineno,
                        )
                    )
        self.generic_visit(node)

    def _process_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_async: bool = False,
        in_class: bool = False,
    ) -> None:
        """Process function/method definitions.

        Args:
            node: AST function node
            is_async: Whether the function is async
            in_class: Whether the function is a method
        """
        source = self._get_source_slice(node)

        # Convert methods to standalone functions
        if in_class:
            entity_type = "function"  # Save as function, not method
            source = MethodConverter.method_to_function(source)
            full_name = (
                f"{self.current_class}_{node.name}" if self.current_class else node.name
            )
        else:
            entity_type = "function"
            full_name = node.name

        self.entities.append(
            Entity(
                name=node.name,
                type=entity_type,
                source=source,
                full_name=full_name,
                source_file=self.path,
                line_number=node.lineno,
                decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            )
        )

    def _get_source_slice(self, node: ast.stmt) -> str:
        """Get source code for a node.

        Args:
            node: AST node

        Returns:
            Source code string for the node
        """
        if not self.source_lines:
            return ""
        start_line = node.lineno - 1
        end_line = node.end_lineno or node.lineno
        start_line = max(0, start_line)
        end_line = min(len(self.source_lines), end_line)
        lines = self.source_lines[start_line:end_line]
        return "".join(lines)

    @staticmethod
    def _get_decorator_name(decorator: ast.expr) -> str:
        """Get decorator name from AST node."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        return ""

    @staticmethod
    def _is_constant_name(name: str) -> bool:
        """Check if a name follows constant naming convention."""
        return bool(re.match("^[A-Z_][A-Z0-9_]*$", name))


def is_python_file(path: Path) -> bool:
    """Check if a file is a Python file.

    Args:
        path: File path to check

    Returns:
        True if the file is a Python file
    """
    if path.suffix == ".py":
        return True
    try:
        with open(path, "rb") as f:
            first_line = f.readline()
            if first_line.startswith(b"#!"):
                return b"python" in first_line
    except OSError:
        pass
    return False


def extract_from_file(path: Path) -> ExtractionResult:
    """Extract entities from a single Python file.

    Args:
        path: Path to the Python file

    Returns:
        ExtractionResult containing extracted entities
    """
    result = ExtractionResult(str(path))
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.errors.append(f"Syntax error: {e}")
            return result
        result.imports = ImportAnalyzer.extract_imports_from_source(source)
        source_lines = source.split("\n")
        visitor = EntityVisitor(source_lines, str(path))
        visitor.visit(tree)
        result.entities = visitor.entities
    except Exception as e:
        result.errors.append(f"Error processing file: {e}")
    return result


def extract_from_archive(
    archive_path: Path, archive_type: str
) -> list[tuple[str, str]]:
    """Extract Python files from an archive.

    Args:
        archive_path: Path to the archive file
        archive_type: Type of archive ('.zip', '.whl', '.tar.gz', etc.)

    Returns:
        List of tuples (virtual_path, source_code)
    """
    results: list[tuple[str, str]] = []
    if archive_type in {".zip", ".whl"}:
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith(".py"):
                        try:
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            virtual_path = f"{archive_path.name}::{member}"
                            results.append((virtual_path, content))
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Failed to extract from zip archive {archive_path}: {e}")
    elif archive_type in {".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar"}:
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.endswith(".py") and member.isfile():
                        try:
                            f = tf.extractfile(member)
                            if f:
                                content = f.read().decode("utf-8", errors="ignore")
                                virtual_path = f"{archive_path.name}::{member.name}"
                                results.append((virtual_path, content))
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Failed to extract from tar archive {archive_path}: {e}")
    elif archive_type == ".tar.zst":
        if not HAS_ZSTD:
            logger.warning("zstandard library not available for .tar.zst archives")
            return results
        try:
            with open(archive_path, "rb") as f:
                dctx = zstd.ZstdDecompressor()
                with (
                    dctx.stream_reader(f) as reader,
                    tarfile.open(fileobj=reader, mode="r|") as tf,
                ):
                    for member in tf:
                        if member.name.endswith(".py") and member.isfile():
                            try:
                                f_obj = tf.extractfile(member)
                                if f_obj:
                                    content = f_obj.read().decode(
                                        "utf-8", errors="ignore"
                                    )
                                    virtual_path = f"{archive_path.name}::{member.name}"
                                    results.append((virtual_path, content))
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(
                f"Failed to extract from tar.zst archive {archive_path}: {e}"
            )
    return results


def extract_from_archive_member(virtual_path: str, source: str) -> ExtractionResult:
    """Extract entities from a Python file inside an archive.

    Args:
        virtual_path: Virtual path of the file in the archive
        source: Source code as string

    Returns:
        ExtractionResult containing extracted entities
    """
    result = ExtractionResult(virtual_path)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result.errors.append(f"Syntax error: {e}")
        return result
    result.imports = ImportAnalyzer.extract_imports_from_source(source)
    source_lines = source.split("\n")
    visitor = EntityVisitor(source_lines, virtual_path)
    visitor.visit(tree)
    result.entities = visitor.entities
    return result


def process_file_worker(path: Path) -> ExtractionResult:
    """Worker function for processing files in parallel."""
    return extract_from_file(path)


def process_archive_member_worker(args: tuple[str, str]) -> ExtractionResult:
    """Worker function for processing archive members in parallel."""
    virtual_path, source = args
    return extract_from_archive_member(virtual_path, source)


def scan_directory(directory: str) -> tuple[list[Path], list[tuple[str, str]]]:
    """Scan a directory for Python files and archives.

    Args:
        directory: Directory path to scan

    Returns:
        Tuple of (python_files, archive_members)
    """
    base_dir = Path(directory).resolve()
    python_files: list[Path] = []
    archive_members: list[tuple[str, str]] = []

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        root_path = Path(root)
        for filename in files:
            path = root_path / filename
            if path.is_symlink():
                continue
            if is_python_file(path):
                python_files.append(path)
            elif path.suffix in {".zip", ".whl"}:
                members = extract_from_archive(path, path.suffix)
                archive_members.extend(members)
            elif path.suffix in {".gz", ".bz2", ".xz", ".zst"}:
                name = path.name
                if name.endswith((".tar.gz", ".tgz")):
                    archive_type = ".tar.gz"
                elif name.endswith(".tar.bz2"):
                    archive_type = ".tar.bz2"
                elif name.endswith(".tar.xz"):
                    archive_type = ".tar.xz"
                elif name.endswith(".tar.zst"):
                    archive_type = ".tar.zst"
                else:
                    continue
                members = extract_from_archive(path, archive_type)
                archive_members.extend(members)
            elif path.suffix == ".tar":
                members = extract_from_archive(path, ".tar")
                archive_members.extend(members)
    return (python_files, archive_members)


def write_entity(output_dir: Path, entity: Entity) -> Path | None:
    """Write an entity to a file after validating the code.

    Args:
        output_dir: Directory to write to
        entity: Entity to write

    Returns:
        Path to written file, or None if failed or invalid
    """
    entity_dir = output_dir / entity.type
    entity_dir.mkdir(parents=True, exist_ok=True)
    base_filename = entity.full_name.replace("::", "_").replace("/", "_")
    filename = f"{base_filename}.py"
    path = entity_dir / filename
    counter = 1
    while path.exists():
        counter += 1
        path = entity_dir / f"{base_filename}_{counter}.py"

    existing_imports = ImportAnalyzer.extract_imports_from_source(entity.source)
    needed_imports = ImportAnalyzer.detect_needed_imports(entity.source)
    imports = ImportAnalyzer.consolidate_imports(existing_imports, needed_imports)

    lines: list[str] = []
    lines.append(f"# Extracted from: {entity.source_file}:{entity.line_number}\n")
    if imports:
        lines.extend([imp + "\n" for imp in imports])
        lines.append("\n")
    lines.append(entity.source)
    if not entity.source.endswith("\n"):
        lines.append("\n")

    # Validate the complete code before writing
    complete_code = "".join(lines)
    is_valid, error_msg = CodeValidator.validate_python_code(complete_code)

    if not is_valid:
        logger.warning(f"Skipping invalid entity {entity.full_name}: {error_msg}")
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(complete_code)
        return path
    except Exception as e:
        logger.error(f"Error writing entity: {e}")
        return None


def write_imports_file(output_dir: Path, all_imports: set[str]) -> None:
    """Write aggregated imports to a file.

    Args:
        output_dir: Directory to write to
        all_imports: Set of all imports
    """
    organized = ImportAnalyzer.consolidate_imports(all_imports, set())
    path = output_dir / "imports.py"
    content = "# Aggregated imports from extracted entities\n\n" + "".join(
        imp + "\n" for imp in organized
    )

    # Validate imports file
    is_valid, error_msg = CodeValidator.validate_python_code(content)
    if is_valid:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        logger.warning(f"Failed to write imports file: {error_msg}")


def main() -> int:
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Python code entities from files and archives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python extract_entities.py\n\n\n  python extract_entities.py -t\n\n\n  python extract_entities.py --workers 16\n        ",
    )
    parser.add_argument(
        "-t",
        "--temp",
        action="store_true",
        help="Save to ~/tmp/output/ instead of ./output/",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of worker processes",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()

    if args.temp:
        output_dir = Path.home() / "tmp" / "output"
    else:
        output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning directory: {Path(args.directory).resolve()}")
    print(f"Output directory: {output_dir.resolve()}\n")

    python_files, archive_members = scan_directory(args.directory)
    print(
        f"Found {len(python_files):,} Python files and {len(archive_members):,} archive members\n"
    )

    all_entities: list[Entity] = []
    all_imports: set[str] = set()
    entity_count: dict[str, int] = {"function": 0, "class": 0, "constant": 0}
    error_count = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures: dict = {
            executor.submit(process_file_worker, fpath): ("file", str(fpath))
            for fpath in python_files
        }
        for virtual_path, source in archive_members:
            futures[
                executor.submit(process_archive_member_worker, (virtual_path, source))
            ] = (
                "archive",
                virtual_path,
            )

        processed = 0
        for future in as_completed(futures):
            _source_type, source_path = futures[future]
            processed += 1
            try:
                result = future.result()
                all_entities.extend(result.entities)
                all_imports.update(result.imports)
                for entity in result.entities:
                    entity_count[entity.type] += 1
                if result.errors:
                    error_count += len(result.errors)
                    for error in result.errors:
                        logger.error(f"Error in {source_path}: {error}")
                if processed % 50 == 0:
                    logger.debug(f"Processed: {processed}/{len(futures)}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing {source_path}: {e}")

    print(f"\nExtracted {len(all_entities):,} entities:")
    for etype, count in entity_count.items():
        if count > 0:
            print(f"  {etype}: {count}")

    print("\nValidating and writing entities to output directory...")
    written_count = 0
    skipped_count = 0
    for entity in all_entities:
        result = write_entity(output_dir, entity)
        if result:
            written_count += 1
        else:
            skipped_count += 1

    print(f"Saved {written_count}/{len(all_entities)} entities")
    if skipped_count > 0:
        logger.warning(f"Skipped {skipped_count} invalid entities")
    print()

    write_imports_file(output_dir, all_imports)
    print("Saved aggregated imports to imports.py")
    print(f"\nTotal unique imports: {len(all_imports)}")

    if error_count > 0:
        logger.warning(f"Errors encountered: {error_count}")
    return 0


if __name__ == "__main__":
    # Configure loguru for console output
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )
    raise SystemExit(main())
