#!/data/data/com.termux/files/home/.local/bin/python
"""
Translate non-ASCII docstrings and comments in every Python file under the current
directory to English in place. Uses a fixed multiprocessing.Pool of 8 workers, a
backup ``.bak`` copy per modified file, and the ``dh.get_pyfiles`` helper to find
targets. Logging via loguru; non-Python text manipulation via pathlib + ast + re.
"""

import ast
import re
import shutil
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final, cast

from deep_translator import GoogleTranslator  # type: ignore[import-untyped]
from dh import get_pyfiles
from loguru import logger

CHUNK_SIZE: Final[int] = 5000
MAX_WORKERS: Final[int] = 8
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
NON_ASCII_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x7F]")


def translate_text(text: str) -> str:
    """
    Translate ``text`` to English if it contains non-ASCII characters.

    Args:
        text: Source text to inspect and possibly translate.

    Returns:
        The translated text on success, otherwise the original text unchanged.
    """
    if not text.strip() or not NON_ASCII_PATTERN.search(text):
        return text
    try:
        translator: GoogleTranslator = GoogleTranslator(source="auto", target="en")
        translated: str | None = translator.translate(text.strip())
        return translated if translated else text
    except Exception as exc:
        logger.debug(f"Translation error: {exc} for text: {text[:30]}")
        return text


class DocstringCommentTransformer(ast.NodeTransformer):
    """
    AST transformer that translates non-ASCII docstrings on modules, classes,
    and functions in place.

    Attributes:
        modified: ``True`` if any docstring was replaced during traversal.
    """

    def __init__(self) -> None:
        """Initialize the transformer with no modifications recorded."""
        self.modified: bool = False

    def _translate_node_docstring(self, node: ast.AST) -> None:
        """
        Translate the docstring attached to ``node``, if any.

        Args:
            node: An AST node that may carry a docstring (Module/ClassDef/FunctionDef).
        """
        docstring: str | None = ast.get_docstring(node)
        if docstring and NON_ASCII_PATTERN.search(docstring):
            translated: str = translate_text(docstring)
            if translated != docstring:
                self.modified = True
                body: list[ast.stmt] = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body[0].value.value = translated

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:  # type: ignore[override]
        """Translate a function's docstring, then recurse into its body."""
        self._translate_node_docstring(node)
        return cast(ast.FunctionDef, self.generic_visit(node))

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:  # type: ignore[override]
        """Translate a class's docstring, then recurse into its body."""
        self._translate_node_docstring(node)
        return cast(ast.ClassDef, self.generic_visit(node))

    def visit_Module(self, node: ast.Module) -> ast.Module:  # type: ignore[override]
        """Translate the module-level docstring, then recurse into the tree."""
        self._translate_node_docstring(node)
        return cast(ast.Module, self.generic_visit(node))


def translate_comments(content: str) -> tuple[str, bool]:
    """
    Translate non-ASCII text in ``#`` comments line by line.

    Args:
        content: Full source file content.

    Returns:
        A tuple ``(new_content, modified)`` where ``modified`` is ``True`` if any
        comment was rewritten.
    """
    lines: list[str] = content.splitlines(keepends=True)
    new_lines: list[str] = []
    modified: bool = False

    for line in lines:
        if "#" in line:
            parts: list[str] = line.split("#", 1)
            comment: str = parts[1]
            if NON_ASCII_PATTERN.search(comment):
                translated: str = translate_text(comment)
                if translated != comment:
                    new_lines.append(f"{parts[0]}# {translated}\n")
                    modified = True
                    continue
        new_lines.append(line)

    return "".join(new_lines), modified


def process_file(filepath: Path) -> bool:
    """
    Translate non-ASCII docstrings/comments in ``filepath`` in place.

    A ``.bak`` backup is created before any modification. Docstrings are handled
    via AST rewriting; comments are handled textually. If the AST cannot be
    parsed after comment translation, only the comment changes are written.

    Args:
        filepath: Path to the Python source file.

    Returns:
        ``True`` if the file was modified, otherwise ``False``.
    """
    try:
        backup_path: Path = filepath.with_suffix(filepath.suffix + ".bak")
        shutil.copyfile(filepath, backup_path)

        content: str = filepath.read_text(encoding="utf-8")
        content_after_comments, comments_modified = translate_comments(content)

        try:
            tree: ast.Module = ast.parse(content_after_comments)
            transformer: DocstringCommentTransformer = DocstringCommentTransformer()
            new_tree: ast.AST = transformer.visit(tree)
            if transformer.modified or comments_modified:
                new_content: str = ast.unparse(new_tree)
                filepath.write_text(new_content, encoding="utf-8")
                return True
        except SyntaxError:
            if comments_modified:
                filepath.write_text(content_after_comments, encoding="utf-8")
                return True
    except Exception as exc:
        logger.error(f"Failed to process {filepath}: {exc}")

    return False


def main() -> None:
    """Entry point: locate Python files and translate them in parallel."""
    cwd: Path = Path.cwd()
    py_files: list[Path] = get_pyfiles(cwd)

    if not py_files:
        print("No Python files found.")
        return

    print(f"Processing {len(py_files)} files...")
    modified_count: int = 0

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[bool]] = [
            pool.apply_async(process_file, (f,)) for f in py_files
        ]
        for file_path, async_res in zip(py_files, async_results):
            if async_res.get():
                modified_count += 1
                print(f"✓ Updated: {file_path.name}")

    print(f"Done. Modified {modified_count} files.")


if __name__ == "__main__":
    raise SystemExit(main())
