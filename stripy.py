#!/data/data/com.termux/files/home/.local/bin/python
"""Recursively strip comments and docstrings from Python files in-place.

Uses :mod:`libcst` so that only comments / docstrings are removed without
reformatting the rest of the file.

* If stripping a docstring leaves a function/class body empty, a ``pass``
  statement is inserted so the result stays valid Python.
* The transformed source is re-parsed with :mod:`ast` *and* :mod:`libcst`
  before writing; if it is not valid Python the file is left untouched.
* Files are processed in parallel with a :class:`multiprocessing.Pool` of
  ``WORKERS`` workers using :meth:`multiprocessing.pool.Pool.starmap`.
* Every action and every error is reported through :mod:`loguru`.

Usage::

    strip_comments.py [PATH ...]

Every ``PATH`` may be either a Python file or a directory; directories are
searched recursively for ``*.py`` files.  With no arguments the current
directory is used.
"""

from __future__ import annotations

import ast
import multiprocessing as mp
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import libcst as cst
from loguru import logger


#: Number of worker processes used to transform files in parallel.
WORKERS: int = 8


# ---------------------------------------------------------------------------
# Result reporting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileReport:
    """Outcome of processing a single file."""

    path: Path
    docstrings_removed: int = 0
    comments_removed: int = 0
    pass_inserted: int = 0
    written: bool = False
    skipped: bool = False


# ---------------------------------------------------------------------------
# libcst helpers
# ---------------------------------------------------------------------------


def _pass_stmt() -> cst.SimpleStatementLine:
    """Return a freshly-built ``pass`` statement line."""
    return cst.SimpleStatementLine(body=[cst.Pass()])


def _is_docstring_small(stmt: cst.BaseSmallStatement) -> bool:
    """Return ``True`` for a string-literal expression statement."""
    return isinstance(stmt, cst.Expr) and isinstance(
        stmt.value, (cst.SimpleString, cst.ConcatenatedString)
    )


def _is_docstring_stmt(stmt: cst.BaseStatement) -> bool:
    """Return ``True`` if ``stmt`` is a standalone docstring expression."""
    return (
        isinstance(stmt, cst.SimpleStatementLine)
        and len(stmt.body) == 1
        and _is_docstring_small(stmt.body[0])
    )


def _strip_first_docstring(
    stmts: Sequence[cst.BaseStatement],
    counters: dict[str, int],
    *,
    ensure_body: bool = False,
) -> Sequence[cst.BaseStatement]:
    """Return ``stmts`` with a leading docstring removed.

    When ``ensure_body`` is true and the result would be empty, a ``pass``
    statement is inserted so the enclosing suite stays syntactically valid.
    """
    new = list(stmts)
    if new and _is_docstring_stmt(new[0]):
        new = new[1:]
        counters["docstrings"] += 1
    if ensure_body and not new:
        new = [_pass_stmt()]
        counters["passes"] += 1
    return new


def _strip_suite(body: cst.BaseSuite, counters: dict[str, int]) -> cst.BaseSuite:
    """Remove a leading docstring from a class/function body."""
    if isinstance(body, cst.IndentedBlock):
        new_inner = _strip_first_docstring(body.body, counters, ensure_body=True)
        return body.with_changes(body=new_inner)

    if isinstance(body, cst.SimpleStatementSuite):
        inner = list(body.body)
        if inner and _is_docstring_small(inner[0]):
            inner = inner[1:]
            counters["docstrings"] += 1
        if not inner:
            inner = [cst.Pass()]
            counters["passes"] += 1
        return body.with_changes(body=inner)

    return body


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------


class StripTransformer(cst.CSTTransformer):
    """Remove comments and the leading docstring of modules/classes/functions."""

    def __init__(self) -> None:
        super().__init__()
        self.counters: dict[str, int] = {
            "docstrings": 0,
            "comments": 0,
            "passes": 0,
        }

    # ---- docstrings -------------------------------------------------------

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        return updated_node.with_changes(
            body=_strip_first_docstring(updated_node.body, self.counters)
        )

    def _strip_callable(
        self,
        updated_node: cst.FunctionDef | cst.AsyncFunctionDef | cst.ClassDef,
    ) -> cst.FunctionDef | cst.AsyncFunctionDef | cst.ClassDef:
        new_body = _strip_suite(updated_node.body, self.counters)
        if new_body is updated_node.body:
            return updated_node
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        result = self._strip_callable(updated_node)
        assert isinstance(result, cst.FunctionDef)
        return result

    def leave_AsyncFunctionDef(
        self,
        original_node: cst.AsyncFunctionDef,
        updated_node: cst.AsyncFunctionDef,
    ) -> cst.AsyncFunctionDef:
        result = self._strip_callable(updated_node)
        assert isinstance(result, cst.AsyncFunctionDef)
        return result

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        result = self._strip_callable(updated_node)
        assert isinstance(result, cst.ClassDef)
        return result

    # ---- comments ---------------------------------------------------------

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if updated_node.comment is not None:
            self.counters["comments"] += 1
            return updated_node.with_changes(comment=None)
        return updated_node

    def leave_EmptyLine(
        self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine
    ) -> cst.EmptyLine:
        if updated_node.comment is not None:
            self.counters["comments"] += 1
            return updated_node.with_changes(comment=None)
        return updated_node


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def process_file(path: Path) -> FileReport:
    """Strip comments/docstrings from a single file in-place.

    Runs in a worker process; must therefore be picklable and self-contained.
    """
    report = FileReport(path=path)

    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        logger.error("skip (not utf-8) {}: {}", path, exc)
        report.skipped = True
        return report
    except OSError as exc:
        logger.error("skip (read error) {}: {}", path, exc)
        report.skipped = True
        return report

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        logger.error("skip (parse error) {}: {}", path, exc)
        report.skipped = True
        return report

    transformer = StripTransformer()
    try:
        new_module = module.visit(transformer)
    except Exception as exc:  # noqa: BLE001 - transformer must never abort the pool
        logger.exception("transformer crashed on {}: {}", path, exc)
        report.skipped = True
        return report

    report.docstrings_removed = transformer.counters["docstrings"]
    report.comments_removed = transformer.counters["comments"]
    report.pass_inserted = transformer.counters["passes"]

    new_code = new_module.code
    if new_code == source:
        logger.debug("unchanged {}", path)
        return report

    # --- validate before writing -------------------------------------------
    try:
        ast.parse(new_code)
    except SyntaxError as exc:
        logger.error("skip (invalid output, not writing) {}: {}", path, exc)
        report.skipped = True
        return report
    try:
        cst.parse_module(new_code)
    except cst.ParserSyntaxError as exc:
        logger.error("skip (libcst rejects output, not writing) {}: {}", path, exc)
        report.skipped = True
        return report

    try:
        path.write_text(new_code, encoding="utf-8")
    except OSError as exc:
        logger.error("skip (write error) {}: {}", path, exc)
        report.skipped = True
        return report

    report.written = True
    print(
        f"{path} | {report.docstrings_removed}| {report.comments_removed} | {report.pass_inserted}\n"
    )
    return report


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------


def _collect_python_files(inputs: Sequence[Path]) -> list[Path]:
    """Expand every input into a unique, sorted list of ``*.py`` files.

    Each input may be a Python file or a directory (searched recursively).
    Symlinks are resolved and duplicates removed.
    """
    seen: set[Path] = set()
    collected: list[Path] = []

    for raw in inputs:
        path = raw.expanduser()
        if path.is_file():
            if path.suffix == ".py":
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(resolved)
            else:
                logger.warning("ignoring non-Python file: {}", path)
        elif path.is_dir():
            for candidate in path.rglob("*.py"):
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(resolved)
        else:
            logger.warning("path does not exist: {}", path)

    collected.sort()
    return collected


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _configure_logger() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{process.name}</cyan> | {message}"
        ),
        enqueue=True,  # multiprocessing-safe sink
    )


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logger()

    raw_args = list(sys.argv[1:] if argv is None else argv)
    inputs = [Path(a) for a in raw_args] if raw_args else [Path(".")]

    files = _collect_python_files(inputs)
    if not files:
        logger.warning(
            "no Python files found in: {}",
            ", ".join(str(p) for p in inputs),
        )
        return 0

    chunksize = max(1, len(files) // (WORKERS * 4))

    try:
        with mp.Pool(processes=WORKERS) as pool:
            results: list[FileReport] = pool.starmap(
                process_file,
                ((f,) for f in files),
                chunksize=chunksize,
            )
    except KeyboardInterrupt:
        logger.warning("interrupted by user")
        return 130

    written = sum(1 for r in results if r.written)
    skipped = sum(1 for r in results if r.skipped)
    docstrings = sum(r.docstrings_removed for r in results)
    comments = sum(r.comments_removed for r in results)
    passes = sum(r.pass_inserted for r in results)

    #    print(f"(files} updated={written} skipped={skipped} | {docstrings}/{comments}/{passes}\n")
    return 0 if skipped == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
