#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python script that translates Japanese text in Python source files to English.

The script scans a directory recursively for *.py files (skipping common cache
directories), translates Japanese comments (line-level) and docstrings (via an
ast.NodeTransformer) using GoogleTranslator with source="ja" and target="en",
and rewrites modified files in place. Any residual Japanese text is also
translated via regex substitution. Work is dispatched to a multiprocessing.Pool
with 8 workers using apply_async, and loguru is used for logging.
"""

from __future__ import annotations

import ast
import re
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from loguru import logger

POOL_WORKERS: Final[int] = 8

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)

JAPANESE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def translate_text(text: str) -> str:
    """Translate a Japanese text snippet to English, returning the original on failure."""
    if not text or not text.strip() or not JAPANESE_PATTERN.search(text):
        return text
    try:
        translator = GoogleTranslator(source="ja", target="en")
        translated: str | None = translator.translate(text)
        return translated if translated else text
    except Exception as e:
        logger.error("Translation error: {} for text snippet: {}", e, text[:50])
        return text


class CommentDocstringTransformer(ast.NodeTransformer):
    """AST transformer that translates Japanese module, class, and function docstrings."""

    modified: bool

    def __init__(self) -> None:
        """Initialize the transformer with a clean modified flag."""
        self.modified = False

    def _process_docstring(self, node: Any) -> None:
        """Translate the docstring attached to the given AST node if it is Japanese."""
        docstring: str | None = ast.get_docstring(node)
        if docstring and JAPANESE_PATTERN.search(docstring):
            translated: str = translate_text(docstring)
            if translated != docstring:
                self.modified = True
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    node.body[0].value.value = translated

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """Visit a function definition and translate its docstring."""
        self._process_docstring(node)
        return self.generic_visit(node)  # type: ignore[return-value]

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """Visit a class definition and translate its docstring."""
        self._process_docstring(node)
        return self.generic_visit(node)  # type: ignore[return-value]

    def visit_Module(self, node: ast.Module) -> ast.Module:
        """Visit a module node and translate its docstring."""
        self._process_docstring(node)
        return self.generic_visit(node)  # type: ignore[return-value]


def translate_comments_in_content(content: str) -> tuple[str, bool]:
    """Translate Japanese text appearing after '#' in each line of content.

    Returns a tuple of (possibly-modified content, whether any change was made).
    """
    lines: list[str] = content.splitlines(keepends=True)
    modified: bool = False
    new_lines: list[str] = []

    for line in lines:
        if "#" in line:
            parts: list[str] = line.split("#", 1)
            comment: str = parts[1]
            if JAPANESE_PATTERN.search(comment):
                translated_comment: str = translate_text(comment)
                if translated_comment != comment:
                    new_lines.append(f"{parts[0]}#{translated_comment}")
                    modified = True
                    continue
        new_lines.append(line)

    return ("".join(new_lines), modified)


def translate_file(path: Path) -> bool:
    """Translate Japanese comments and docstrings in a Python file.

    Returns True if the file was modified and rewritten.
    """
    try:
        content: str = path.read_text(encoding="utf-8")
        content_after_comments, comments_modified = translate_comments_in_content(
            content
        )

        try:
            tree: ast.Module = ast.parse(content_after_comments)
            transformer = CommentDocstringTransformer()
            new_tree: ast.Module = transformer.visit(tree)  # type: ignore[assignment]
            docstrings_modified: bool = transformer.modified

            if comments_modified or docstrings_modified:
                new_content: str = ast.unparse(new_tree)
                if JAPANESE_PATTERN.search(new_content):
                    new_content = JAPANESE_PATTERN.sub(
                        lambda m: translate_text(m.group(0)), new_content
                    )
                path.write_text(new_content, encoding="utf-8")
                return True
        except SyntaxError as e:
            logger.error("Syntax error in {}: {}. Skipping AST translation.", path, e)
            if comments_modified:
                path.write_text(content_after_comments, encoding="utf-8")
                return True
            return False
    except Exception as e:
        logger.error("Error processing {}: {}", path, e)
        return False

    return False


def main() -> None:
    """Entry point: locate Python files and dispatch translation tasks to a Pool."""
    start_dir: str = sys.argv[1] if len(sys.argv) > 1 else "."
    start_path: Path = Path(start_dir).resolve()

    if not start_path.exists():
        logger.error("Error: Path '{}' does not exist", start_path)
        sys.exit(1)

    print("Scanning for Python files in: {}", start_path)

    py_files: list[Path] = [
        f
        for f in start_path.rglob("*.py")
        if not any(part in SKIP_DIRS for part in f.parts)
    ]

    if not py_files:
        print("No Python files found.")
        return

    print("Found {} Python files. Starting translation...", len(py_files))

    modified_count: int = 0

    with Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(translate_file, (f,)) for f in py_files]

        for async_result, path in zip(async_results, py_files):
            try:
                if async_result.get():
                    modified_count += 1
                    print("✓ Updated: {}", path)
            except Exception as e:
                logger.error("Task failed for {}: {}", path, e)

    print("=" * 40)
    print("Completed! Modified {} out of {} files", modified_count, len(py_files))


if __name__ == "__main__":
    raise SystemExit(main())
