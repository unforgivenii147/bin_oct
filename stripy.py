#!/data/data/com.termux/files/home/.local/bin/python
"""Recursively strip comments and docstrings from Python files in-place.

Uses libcst so that only comments / docstrings are removed without
reformatting the rest of the file.

* If stripping a docstring leaves a function/class body empty, a ``pass``
  statement is inserted so the result stays valid Python.
* The transformed source is re-parsed with :mod:`ast` before writing; if it
  is not valid Python the file is left untouched.
* Files are processed in parallel with a :class:`multiprocessing.Pool` of
  8 workers using ``apply_async``.
* Every action and every error is reported through :mod:`loguru`.
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


# ---------------------------------------------------------------------------
# Result reporting
# ---------------------------------------------------------------------------


@dataclass
class FileReport:
    path: Path
    docstrings_removed: int = 0
    comments_removed: int = 0
    pass_inserted: int = 0
    written: bool = False
    skipped: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass_stmt() -> cst.SimpleStatementLine:
    return cst.SimpleStatementLine(body=[cst.Pass()])


def _is_docstring_small(stmt: cst.BaseSmallStatement) -> bool:
    return isinstance(stmt, cst.Expr) and isinstance(
        stmt.value, (cst.SimpleString, cst.ConcatenatedString)
    )


def _is_docstring_stmt(stmt: cst.BaseStatement) -> bool:
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    return _is_docstring_small(stmt.body[0])


def _strip_first_docstring(
    stmts: Sequence[cst.BaseStatement],
    counters: dict,
    ensure_body: bool = False,
) -> Sequence[cst.BaseStatement]:
    new = list(stmts)
    if new and _is_docstring_stmt(new[0]):
        new = new[1:]
        counters["docstrings"] += 1
    if ensure_body and not new:
        new = [_pass_stmt()]
        counters["passes"] += 1
    return new


def _strip_suite(body: cst.BaseSuite, counters: dict) -> cst.BaseSuite:
    if isinstance(body, cst.IndentedBlock):
        new_inner = _strip_first_docstring(body.body, counters, ensure_body=True)
        return body.with_changes(body=new_inner)

    if isinstance(body, cst.SimpleStatementSuite):
        new_inner = list(body.body)
        if new_inner and _is_docstring_small(new_inner[0]):
            new_inner = new_inner[1:]
            counters["docstrings"] += 1
        if not new_inner:
            new_inner = [cst.Pass()]
            counters["passes"] += 1
        return body.with_changes(body=new_inner)

    return body


# ---------------------------------------------------------------------------
# Transformer
# ---------------------------------------------------------------------------


class StripTransformer(cst.CSTTransformer):
    def __init__(self) -> None:
        super().__init__()
        self.counters = {"docstrings": 0, "comments": 0, "passes": 0}

    # ---- docstrings -------------------------------------------------------

    def leave_Module(self, original_node, updated_node):
        return updated_node.with_changes(
            body=_strip_first_docstring(
                updated_node.body, self.counters, ensure_body=False
            )
        )

    def _strip_func(self, updated_node):
        new_body = _strip_suite(updated_node.body, self.counters)
        if new_body is updated_node.body:
            return updated_node
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(self, original_node, updated_node):
        return self._strip_func(updated_node)

    def leave_AsyncFunctionDef(self, original_node, updated_node):
        return self._strip_func(updated_node)

    def leave_ClassDef(self, original_node, updated_node):
        new_body = _strip_suite(updated_node.body, self.counters)
        if new_body is updated_node.body:
            return updated_node
        return updated_node.with_changes(body=new_body)

    # ---- comments ---------------------------------------------------------

    def leave_TrailingWhitespace(self, original_node, updated_node):
        if updated_node.comment is not None:
            self.counters["comments"] += 1
            return updated_node.with_changes(comment=None)
        return updated_node

    def leave_EmptyLine(self, original_node, updated_node):
        if updated_node.comment is not None:
            self.counters["comments"] += 1
            return updated_node.with_changes(comment=None)
        return updated_node


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def process_file(path_str: str) -> FileReport:
    path = Path(path_str)
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("transformer crashed on {}: {}", path, exc)
        report.skipped = True
        return report

    report.docstrings_removed = transformer.counters["docstrings"]
    report.comments_removed = transformer.counters["comments"]
    report.pass_inserted = transformer.counters["passes"]

    new_code = new_module.code
    if new_code == source:
        logger.debug("unchanged {} (docstrings=0, comments=0)", path)
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
    logger.info(
        "updated {} | docstrings removed: {} | comments removed: {} | pass inserted: {}",
        path,
        report.docstrings_removed,
        report.comments_removed,
        report.pass_inserted,
    )
    return report


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
        enqueue=True,  # safe across processes
    )


def main() -> int:
    _configure_logger()

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    if not root.is_dir():
        logger.error("not a directory: {}", root)
        return 1

    files = sorted(str(p) for p in root.rglob("*.py"))
    logger.info("found {} python file(s) under {}", len(files), root)

    results: list[FileReport] = []
    with mp.Pool(processes=8) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in files]
        for ar in async_results:
            try:
                results.append(ar.get())
            except Exception as exc:  # noqa: BLE001
                logger.exception("worker raised: {}", exc)

    written = sum(1 for r in results if r.written)
    skipped = sum(1 for r in results if r.skipped)
    docstrings = sum(r.docstrings_removed for r in results)
    comments = sum(r.comments_removed for r in results)
    passes = sum(r.pass_inserted for r in results)

    logger.info(
        "done | files={} updated={} skipped={} | docstrings removed={} "
        "comments removed={} pass inserted={}",
        len(files),
        written,
        skipped,
        docstrings,
        comments,
        passes,
    )
    return 0 if skipped == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
