#!/data/data/com.termux/files/home/.local/bin/python
"""
strip_comments.py

Strip inline comments, all comments, and/or docstrings from Python source
files using libcst.

Behaviour
---------

* Default
    Strip *inline* (trailing) comments only -- comments that share a physical
    line with code::

        x = 1  # removed

    Standalone comments (on their own line) and docstrings are preserved.

* ``-c`` / ``--remove-all-comments``
    Also strip standalone comments.  Shebangs, encoding declarations and
    common tool directives (``# fmt``, ``# type``, ``# noqa``, ``# pylint``,
    ``# ruff``, ``# isort``, ``# mypy``, ``# pyright``, ``# pragma``) are
    always preserved, regardless of this flag.

    Note: ``# fmt: off`` / ``# fmt: on`` regions are *not* respected -- the
    directives themselves are preserved, but any non-protected comment
    inside such a region is still stripped.

* ``-d`` / ``--remove-docstrings``
    Additionally strip docstrings from ``def`` and ``class`` bodies.  The
    module docstring is preserved.  If the docstring is the only statement
    in a body, it is replaced with ``pass`` so the module stays valid.
    One-liner bodies (``def f(): "doc"`` / ``class A: "doc"``) are handled
    as well.

* ``-c -d``
    Both of the above.

Files are written back in place only when the transformed source still
parses as valid Python (checked with ``ast.parse``).  Encoding (BOM + PEP 263
declarations) is preserved and writes are atomic (``mkstemp`` + ``os.replace``).
Work is parallelised across 8 processes; file paths are streamed to the pool
via ``imap_unordered`` so memory usage stays flat even for very large trees.

Usage::

    strip_comments.py [-c] [-d] [PATH ...]

If no ``PATH`` is given, the current directory is walked recursively.  Each
``PATH`` may be a file or a directory (walked recursively).  Duplicate paths
are processed once.

Requires Python 3.12+ and ``libcst``.
"""

from __future__ import annotations

import argparse
import ast
import functools
import io
import multiprocessing as mp
import os
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterable, Iterator

import libcst as cst


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

NUM_WORKERS = 8
CHUNKSIZE = 4

#: File suffixes treated as Python source during recursive discovery.
PYTHON_SUFFIXES: tuple[str, ...] = (".py", ".pyi")

#: Directories silently pruned during recursive discovery.  Users who want
#: to process files inside these can still pass them explicitly.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
        ".eggs",
    }
)

#: Comment prefixes that are never stripped, even with ``-c``.  These carry
#: meaning for external tools (shebangs, codings, formatters, type-checkers,
#: linters, coverage) and removing them silently breaks those tools.
PROTECTED_COMMENT_PREFIXES: tuple[str, ...] = (
    "#!",  # shebang
    "# -*-",  # Emacs-style coding declaration (PEP 263)
    "# coding",  # simple coding declaration (PEP 263)
    "# fmt",  # black / ruff formatter directives
    "# type",  # mypy / pyright / pyre type directives
    "# noqa",  # flake8 / ruff noqa
    "# pylint",  # pylint directives
    "# ruff",  # ruff directives (e.g. ``# ruff: noqa``)
    "# isort",  # isort directives
    "# mypy",  # mypy per-file directives
    "# pyright",  # pyright directives
    "# pragma",  # e.g. ``# pragma: no cover``
)


# --------------------------------------------------------------------------- #
# Docstring detection helpers
# --------------------------------------------------------------------------- #


def _is_docstring_literal(node: cst.BaseExpression) -> bool:
    """
    Return ``True`` if *node* is a string literal that CPython would treat
    as ``__doc__``.

    Rules:
      * ``SimpleString`` is a docstring unless it is a *bytes* literal
        (``b"..."``) -- CPython stores bytes literals but does not use them
        as ``__doc__``.
      * ``ConcatenatedString`` (``"a" "b"``) is a docstring only if *both*
        halves are docstring literals, which excludes ``f"a" "b"`` (that
        produces a ``FormattedString`` / ``JoinedStr``, not a plain string).
      * F-strings (``FormattedString``) are never docstrings.
      * Everything else (tuples, numbers, ``Ellipsis``, ...) is not a
        docstring.
    """
    if isinstance(node, cst.SimpleString):
        return "b" not in node.prefix.lower()
    if isinstance(node, cst.ConcatenatedString):
        return _is_docstring_literal(node.left) and _is_docstring_literal(node.right)
    return False


def _is_docstring_line(line: cst.SimpleStatementLine) -> bool:
    """Return ``True`` iff *line* starts with a docstring expression."""
    if not line.body:
        return False
    first = line.body[0]
    return isinstance(first, cst.Expr) and _is_docstring_literal(first.value)


def _has_trailing_comment(node: cst.CSTNode) -> bool:
    """Best-effort check for a trailing comment on *node*."""
    tw = getattr(node, "trailing_whitespace", None)
    return tw is not None and getattr(tw, "comment", None) is not None


# --------------------------------------------------------------------------- #
# Docstring removal
# --------------------------------------------------------------------------- #


def _strip_docstring_from_block(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    """
    Remove the leading docstring from an indented body, returning the new
    block and whether anything was removed.

    Cases handled:
      * ``def f():\\n    "doc"``              -> ``pass`` (body would be empty)
      * ``def f():\\n    "doc"\\n    x = 1``  -> docstring line dropped
      * ``def f():\\n    "doc"; x = 1``       -> only the docstring removed
      * docstring line with a trailing comment -> converted to ``pass`` so
        the comment is preserved
      * leading comments on the docstring line  -> transferred to the next
        statement when the line is dropped
    """
    if not block.body:
        return block, False

    first = block.body[0]
    if not isinstance(first, cst.SimpleStatementLine):
        return block, False
    if not _is_docstring_line(first):
        return block, False

    remaining_small = list(first.body[1:])
    rest = list(block.body[1:])

    # (a) The docstring line had other small statements (``"doc"; x = 1``).
    if remaining_small:
        new_first = first.with_changes(body=remaining_small)
        return block.with_changes(body=[new_first, *rest]), True

    # (b) The line becomes empty.  If the body would be empty, or the line
    #     carries a trailing comment we want to preserve, substitute ``pass``.
    if not rest or _has_trailing_comment(first):
        new_first = first.with_changes(body=[cst.Pass()])
        return block.with_changes(body=[new_first, *rest]), True

    # (c) Drop the line entirely; transfer its leading comment lines to the
    #     next statement so we don't lose them.
    if first.leading_lines:
        next_stmt = rest[0]
        existing = list(getattr(next_stmt, "leading_lines", ()) or ())
        merged = list(first.leading_lines) + existing
        try:
            rest[0] = next_stmt.with_changes(leading_lines=merged)
        except AttributeError:
            # Some node type we don't recognise -- skip the transfer rather
            # than fail the whole transformation.
            pass

    return block.with_changes(body=rest), True


def _strip_docstring_from_suite(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    """
    Remove the leading docstring from a one-liner body (``def f(): "doc"``).

    Returns the new suite and whether anything was removed.
    """
    if not suite.body:
        return suite, False

    first = suite.body[0]
    if not (isinstance(first, cst.Expr) and _is_docstring_literal(first.value)):
        return suite, False

    remaining = list(suite.body[1:])
    if not remaining:
        remaining = [cst.Pass()]
    return suite.with_changes(body=remaining), True


def _strip_docstring(
    body: cst.BaseSuite,
) -> tuple[cst.BaseSuite, bool]:
    """Dispatch to the correct body-type handler."""
    if isinstance(body, cst.IndentedBlock):
        return _strip_docstring_from_block(body)
    if isinstance(body, cst.SimpleStatementSuite):
        return _strip_docstring_from_suite(body)
    return body, False


# --------------------------------------------------------------------------- #
# The CST transformer
# --------------------------------------------------------------------------- #


class CommentAndDocstringRemover(cst.CSTTransformer):
    """
    Single-pass transformer that strips comments and/or docstrings.

    The transformer is stateful and counts what it removed.  Create one
    instance per file; ``comments_removed`` and ``docstrings_removed`` are
    exposed as public attributes.

    Comment handling:
      * Inline comments live in ``TrailingWhitespace.comment`` and are always
        stripped (unless protected).
      * Standalone comments live in ``EmptyLine.comment`` and are only
        stripped when ``remove_all_comments`` is ``True``.

    Docstring handling:
      * Only ``FunctionDef`` and ``ClassDef`` bodies are touched.  The
        module docstring is preserved by design.
    """

    def __init__(
        self,
        *,
        remove_all_comments: bool,
        remove_docstrings: bool,
    ) -> None:
        super().__init__()
        self._remove_all_comments = remove_all_comments
        self._remove_docstrings = remove_docstrings
        self.comments_removed: int = 0
        self.docstrings_removed: int = 0

    # -- Comment handling -------------------------------------------------- #

    @staticmethod
    def _is_protected(comment_text: str) -> bool:
        # ``str.startswith`` accepts a tuple of prefixes.
        return comment_text.startswith(PROTECTED_COMMENT_PREFIXES)

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if updated_node.comment is None:
            return updated_node
        if self._is_protected(updated_node.comment.value):
            return updated_node
        self.comments_removed += 1
        # Clear both the comment and the whitespace that preceded it, so
        # ``x = 1  # c`` becomes ``x = 1`` (not ``x = 1  `` with dangling
        # spaces).
        return updated_node.with_changes(
            whitespace=cst.SimpleWhitespace(""),
            comment=None,
        )

    def leave_EmptyLine(
        self,
        original_node: cst.EmptyLine,
        updated_node: cst.EmptyLine,
    ) -> cst.EmptyLine:
        # Standalone comments are only stripped with ``-c``.  Trailing
        # whitespace on such lines is left untouched so blank lines keep
        # their indentation.
        if not self._remove_all_comments:
            return updated_node
        if updated_node.comment is None:
            return updated_node
        if self._is_protected(updated_node.comment.value):
            return updated_node
        self.comments_removed += 1
        return updated_node.with_changes(comment=None)

    # -- Docstring handling ------------------------------------------------ #

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        if not self._remove_docstrings:
            return updated_node
        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef:
        if not self._remove_docstrings:
            return updated_node
        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)
        return updated_node


# --------------------------------------------------------------------------- #
# Filesystem helpers
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, data: bytes) -> None:
    """
    Atomically replace *path* with *data*.

    Writes to a hidden temp file in the same directory, copies the original
    mode bits, then renames the temp file onto the target.  ``os.replace``
    is atomic on POSIX and on the same volume on Windows, so a crash can
    never leave a partially-written source file behind.
    """
    try:
        mode: int | None = path.stat().st_mode
    except OSError:
        mode = None

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Per-file worker (must be a top-level function to be picklable)
# --------------------------------------------------------------------------- #


def process_file(
    path: Path,
    *,
    remove_all_comments: bool,
    remove_docstrings: bool,
) -> tuple[Path, int, int, str | None]:
    """
    Process a single file end-to-end.

    Returns ``(path, comments_removed, docstrings_removed, error_or_None)``.
    The file is only rewritten when something actually changed *and* the
    produced source still parses as valid Python.
    """
    # 1. Read raw bytes.
    try:
        source_bytes = path.read_bytes()
    except OSError as exc:
        return path, 0, 0, f"read error: {exc}"

    # 2. Detect encoding (respects BOM and PEP 263 coding declarations).
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, 0, f"encoding error: {exc}"

    # 3. Parse with libcst.
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, 0, f"libcst parse error: {exc}"
    except Exception as exc:  # defensive: never crash a worker
        return path, 0, 0, f"parse error: {type(exc).__name__}: {exc}"

    # 4. Transform the CST.
    transformer = CommentAndDocstringRemover(
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
    )
    try:
        new_module = module.visit(transformer)
    except Exception as exc:  # defensive
        return path, 0, 0, f"transform error: {type(exc).__name__}: {exc}"

    if transformer.comments_removed == 0 and transformer.docstrings_removed == 0:
        return path, 0, 0, None  # nothing to do; leave the file untouched

    # 5. Generate and validate the new source BEFORE touching the file.
    new_source = new_module.code
    try:
        ast.parse(new_source, filename=str(path))
    except SyntaxError as exc:
        return path, 0, 0, f"post-transform validation failed: {exc}"

    # 6. Atomic write-back, preserving the original encoding.
    try:
        _atomic_write(path, new_source.encode(encoding))
    except (OSError, UnicodeEncodeError) as exc:
        return path, 0, 0, f"write error: {exc}"

    return path, transformer.comments_removed, transformer.docstrings_removed, None


# --------------------------------------------------------------------------- #
# Path discovery
# --------------------------------------------------------------------------- #


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    """
    Yield unique Python files reachable from *roots*.

    * A file argument is yielded directly (if it has a recognised suffix).
    * A directory argument is walked recursively using ``Path.walk`` (3.12+),
      with the common non-source directories in ``SKIP_DIRS`` pruned and
      per-directory errors surfaced via a warning.
    * Duplicate paths (e.g. a file passed explicitly that also lives inside
      a directory argument) are yielded only once.
    * The generator is lazy, so the multiprocessing pool's feeder thread can
      stream paths to workers without materialising the entire tree.
    """
    seen: set[Path] = set()

    def _on_error(exc: OSError) -> None:
        print(f"warning: {exc}", file=sys.stderr)

    for root in roots:
        try:
            if root.is_file():
                if root.suffix in PYTHON_SUFFIXES:
                    key = root.resolve()
                    if key not in seen:
                        seen.add(key)
                        yield root
            elif root.is_dir():
                for dirpath, dirnames, filenames in root.walk(on_error=_on_error):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for name in filenames:
                        if not name.endswith(PYTHON_SUFFIXES):
                            continue
                        candidate = dirpath / name
                        try:
                            key = candidate.resolve()
                        except OSError:
                            continue
                        if key in seen:
                            continue
                        seen.add(key)
                        yield candidate
            else:
                print(f"warning: skipping non-existent path: {root}", file=sys.stderr)
        except OSError as exc:
            print(f"warning: cannot access {root}: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strip_comments",
        description=(
            "Remove inline comments (default), all comments (-c), and/or "
            "docstrings (-d) from Python files using libcst. Files are "
            "modified in place. Shebangs and tool directives are preserved."
        ),
    )
    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help=(
            "Also remove standalone comments, not just inline ones. "
            "Shebangs and tool directives (# fmt, # type, # noqa, ...) are "
            "always preserved."
        ),
    )
    parser.add_argument(
        "-d",
        "--remove-docstrings",
        action="store_true",
        help=(
            "Remove docstrings from function and class bodies. The module "
            "docstring is preserved. A docstring-only body is replaced "
            "with 'pass'."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=(
            "Files or directories to process. Defaults to the current "
            "directory, walked recursively."
        ),
    )
    return parser


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots: list[Path] = args.paths or [Path.cwd()]

    # ``functools.partial`` is picklable since Python 3.4; it lets us feed
    # ``imap_unordered`` a single-argument callable while still binding the
    # two mode flags.
    worker = functools.partial(
        process_file,
        remove_all_comments=args.remove_all_comments,
        remove_docstrings=args.remove_docstrings,
    )

    total_files = 0
    changed_files = 0
    total_comments = 0
    total_docstrings = 0
    error_count = 0

    # ``imap_unordered`` streams tasks out and results in as they finish,
    # keeping memory usage flat and reporting progress incrementally.
    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            iter_python_files(roots),
            chunksize=CHUNKSIZE,
        )
        for path, comments, docstrings, error in results:
            total_files += 1
            if error is not None:
                error_count += 1
                print(f"ERROR  {path}: {error}", file=sys.stderr)
                continue
            if comments == 0 and docstrings == 0:
                continue
            changed_files += 1
            total_comments += comments
            total_docstrings += docstrings
            bits: list[str] = []
            if comments:
                bits.append(f"{comments} comment(s)")
            if docstrings:
                bits.append(f"{docstrings} docstring(s)")
            print(f"{path}: removed {', '.join(bits)}")

    if total_files == 0:
        print("No Python files found.", file=sys.stderr)
        return 1

    summary = (
        f"\nProcessed {total_files} file(s): "
        f"{changed_files} changed, "
        f"{total_comments} comment(s) and "
        f"{total_docstrings} docstring(s) removed, "
        f"{error_count} error(s)."
    )
    print(summary, file=sys.stderr if error_count else sys.stdout)

    return 2 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
