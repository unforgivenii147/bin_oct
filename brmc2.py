#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that removes docstrings from Python source files.

The script should:
- Accept file or directory paths as command-line arguments (default: current directory).
- Recursively discover all `.py` files under the provided paths.
- Parse each file with `ast`, strip docstrings from modules, classes, and functions,
  preserving the module-level docstring, and insert `pass` where a body becomes empty.
- Validate both original and transformed code by parsing and compiling it.
- Process files concurrently using `multiprocessing.Pool.apply_async` with a fixed
  pool of 8 workers (no CLI flags to control parallelism).
- Use `loguru` for logging, `pathlib` for all path handling, and full type hints
  throughout so the script passes a strict type checker.
- Exit with code 0 if all files succeed, otherwise 1.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

MAX_WORKERS: int = 8
"""Fixed number of worker processes used for concurrent file processing."""


class DocstringRemover(ast.NodeTransformer):
    """AST transformer that strips docstrings from modules, classes, and functions.

    The module-level docstring is preserved. When removing a docstring leaves a
    class or function body empty, a `pass` statement is inserted so the body
    remains syntactically valid.
    """

    def __init__(self) -> None:
        """Initialize the transformer with default traversal state."""
        self.is_module: bool = True
        self.preserve_module_docstring: bool = True

    def visit_Module(self, node: ast.Module) -> ast.Module:
        """Visit a module node, preserving its top-level docstring.

        Args:
            node: The module AST node being visited.

        Returns:
            The transformed module AST node.
        """
        self.is_module = True
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            module_docstring = node.body[0]
            remaining_body = self._visit_body(node.body[1:])
            node.body = [module_docstring] + remaining_body
        else:
            node.body = self._visit_body(node.body)
        self.is_module = False
        return node

    def _visit_body(self, body: Sequence[ast.stmt]) -> list[ast.stmt]:
        """Visit each statement in a body list.

        Args:
            body: The sequence of AST statements to visit.

        Returns:
            A new list of visited statements.
        """
        new_body: list[ast.stmt] = []
        for stmt in body:
            new_body.append(self.visit(stmt))
        return new_body

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """Visit a synchronous function definition.

        Args:
            node: The function definition AST node.

        Returns:
            The transformed function definition node.
        """
        return self._process_function_like(node)

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        """Visit an asynchronous function definition.

        Args:
            node: The async function definition AST node.

        Returns:
            The transformed async function definition node.
        """
        return self._process_function_like(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """Visit a class definition.

        Args:
            node: The class definition AST node.

        Returns:
            The transformed class definition node.
        """
        node.body = self._remove_docstring_from_body(node.body)
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _process_function_like(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ast.FunctionDef | ast.AsyncFunctionDef:
        """Process a function-like node by stripping its docstring.

        Args:
            node: A function or async function definition node.

        Returns:
            The transformed function-like node.
        """
        node.body = self._remove_docstring_from_body(node.body)
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _remove_docstring_from_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        """Remove a leading docstring from a body, inserting `pass` if empty.

        Args:
            body: The list of statements forming a function or class body.

        Returns:
            The new body list with any leading docstring removed.
        """
        if not body:
            return body
        if (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        new_body: list[ast.stmt] = [self.visit(stmt) for stmt in body]
        if not new_body:
            new_body = [ast.Pass()]
        return new_body


def remove_docstrings_from_code(source_code: str) -> str | None:
    """Remove docstrings from the given Python source code.

    Args:
        source_code: The Python source code as a string.

    Returns:
        The transformed source code, or None if parsing or transformation failed.
    """
    try:
        tree = ast.parse(source_code)
        transformer = DocstringRemover()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        compile(new_tree, "<transformed>", "exec")
        return ast.unparse(new_tree)
    except SyntaxError as exc:
        logger.error(f"Syntax error in transformed code: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error processing code: {exc}")
        return None


def validate_python_code(code: str) -> bool:
    """Validate that the given source code parses and compiles.

    Args:
        code: The Python source code to validate.

    Returns:
        True if the code is valid, False otherwise.
    """
    try:
        ast.parse(code)
        compile(code, "<string>", "exec")
        return True
    except (SyntaxError, ValueError) as exc:
        logger.error(f"Code validation failed: {exc}")
        return False


def process_file(path: Path) -> tuple[Path, bool, str | None]:
    """Process a single Python file, removing docstrings in place.

    Args:
        path: Path to the Python file to process.

    Returns:
        A tuple of (path, success, error_message). `error_message` is None on success.
    """
    try:
        original_code = path.read_text(encoding="utf-8")
        if not validate_python_code(original_code):
            return (path, False, "Original code validation failed")
        modified_code = remove_docstrings_from_code(original_code)
        if modified_code is None:
            return (path, False, "Docstring removal failed")
        if not validate_python_code(modified_code):
            return (path, False, "Modified code validation failed")
        path.write_text(modified_code, encoding="utf-8")
        return (path, True, None)
    except Exception as exc:  # noqa: BLE001
        return (path, False, str(exc))


def find_python_files(paths: Iterable[Path]) -> list[Path]:
    """Recursively find all Python files under the given paths.

    Args:
        paths: An iterable of files or directories to search.

    Returns:
        A sorted list of unique Python file paths.
    """
    python_files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            python_files.append(path)
        elif path.is_dir():
            python_files.extend(path.rglob("*.py"))
    return sorted(set(python_files))


def main() -> int:
    """Entry point for the docstring removal script.

    Returns:
        Exit code: 0 if all files were processed successfully, otherwise 1.
    """
    if len(sys.argv) > 1:
        input_paths: list[Path] = [Path(arg) for arg in sys.argv[1:]]
    else:
        input_paths = [Path.cwd()]

    for path in input_paths:
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            return 1

    python_files = find_python_files(input_paths)
    if not python_files:
        logger.warning("No Python files found to process")
        return 0

    print(f"Found {len(python_files)} Python file(s) to process")

    successful = 0
    failed = 0

    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(process_file, (path,)) for path in python_files
        ]
        for async_result in async_results:
            path, success, error = async_result.get()
            if success:
                print(f"✓ Processed: {path}")
                successful += 1
            else:
                logger.error(f"✗ Failed: {path} - {error}")
                failed += 1

    print(f"\n{'=' * 40}")
    print("Processing complete:")
    print(f"  Successful: {successful}")
    print(f"  Failed:     {failed}")
    print(f"  Total:      {len(python_files)}")
    print(f"{'=' * 40}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
