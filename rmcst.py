#!/data/data/com.termux/files/home/.local/bin/python
"""
strip_inline_comments.py

Remove inline (trailing) comments from Python source files using libcst.

An "inline" comment is one that appears on the same physical line as code:

    DOWNLOAD_DIR = Path.cwd()  # Overwritten by -d / --dir
    ^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^ removed

    # A standalone comment on its own line is preserved.
    x = 1

Files are rewritten in place, but only when at least one inline comment was
removed *and* the transformed source still parses as valid Python. Work is
parallelised across 8 worker processes; file paths are streamed to the pool
via `imap_unordered`, so memory stays flat even for very large trees.

Usage:
    strip_inline_comments.py [PATH ...]

If no PATH is given, the current directory is walked recursively. PATH may
be a file or a directory (which is walked recursively). Duplicate paths are
processed once.

Requires: Python 3.12+, libcst.
"""

from __future__ import annotations

import argparse
import ast
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

# Directories silently pruned during recursive discovery. Users who *want* to
# process files inside these can still pass them explicitly.
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


# --------------------------------------------------------------------------- #
# CST transformation
# --------------------------------------------------------------------------- #


class InlineCommentRemover(cst.CSTTransformer):
    """
    Strip every trailing (inline) comment from a parsed module.

    libcst attaches a line's trailing comment to a `TrailingWhitespace` node,
    which is reachable from:
      * `SimpleStatementLine.trailing_whitespace`  ->  `x = 1  # c`
      * `SimpleStatementSuite.trailing_whitespace` ->  `if x: y = 1  # c`
      * `IndentedBlock.header`                     ->  `if x:  # c\n    ...`

    Standalone comments live in `EmptyLine.comment` / `leading_lines`, so
    they are naturally untouched by this transformer.

    The counter is exposed via `comments_removed`; one transformer instance
    should be created per file.
    """

    def __init__(self) -> None:
        super().__init__()
        self.comments_removed: int = 0

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if updated_node.comment is None:
            return updated_node

        self.comments_removed += 1
        # Clear both the comment and the whitespace that preceded it so
        # `x = 1  # c` becomes `x = 1`, not `x = 1  ` with dangling spaces.
        return updated_node.with_changes(
            whitespace=cst.SimpleWhitespace(""),
            comment=None,
        )


# --------------------------------------------------------------------------- #
# Filesystem helpers
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, data: bytes) -> None:
    """
    Atomically replace `path` with `data`.

    The new content is written to a hidden temp file in the same directory,
    the original mode bits are copied over, and the temp file is renamed onto
    the target. `os.replace` is atomic on POSIX and on Windows (same volume),
    so a crash can never leave a partially-written source file behind.
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
# Per-file worker
# --------------------------------------------------------------------------- #


def process_file(path: Path) -> tuple[Path, int, str | None]:
    """
    Process a single file end-to-end.

    Returns ``(path, comments_removed, error_or_None)``. The file is only
    rewritten if at least one comment was removed *and* the produced source
    still parses as valid Python.

    This function must be importable from the top level so it can be pickled
    to worker processes (it is, on all platforms including spawn-based ones).
    """
    # 1. Read raw bytes.
    try:
        source_bytes = path.read_bytes()
    except OSError as exc:
        return path, 0, f"read error: {exc}"

    # 2. Detect encoding (respects BOM + PEP 263 coding declarations).
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, f"encoding error: {exc}"

    # 3. Parse with libcst.
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, f"libcst parse error: {exc}"
    except Exception as exc:  # defensive: never crash a worker
        return path, 0, f"parse error: {type(exc).__name__}: {exc}"

    # 4. Transform the CST.
    transformer = InlineCommentRemover()
    try:
        new_module = module.visit(transformer)
    except Exception as exc:  # defensive
        return path, 0, f"transform error: {type(exc).__name__}: {exc}"

    if transformer.comments_removed == 0:
        return path, 0, None  # nothing changed; leave the file untouched

    # 5. Generate and validate the new source BEFORE touching the file.
    new_source = new_module.code
    try:
        ast.parse(new_source, filename=str(path))
    except SyntaxError as exc:
        return path, 0, f"post-transform validation failed: {exc}"

    # 6. Atomic write-back, preserving the original encoding.
    try:
        _atomic_write(path, new_source.encode(encoding))
    except (OSError, UnicodeEncodeError) as exc:
        return path, 0, f"write error: {exc}"

    return path, transformer.comments_removed, None


# --------------------------------------------------------------------------- #
# Path discovery
# --------------------------------------------------------------------------- #


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    """
    Yield unique ``.py`` files reachable from ``roots``.

    * A file argument is yielded directly (if it has a ``.py`` suffix).
    * A directory argument is walked recursively using ``Path.walk`` (3.12+),
      with the common non-source directories in ``SKIP_DIRS`` pruned and
      per-directory errors surfaced via a warning.
    * Duplicate paths (e.g. a file passed explicitly that is also inside a
      directory argument) are yielded only once.
    * The generator is lazy, so the multiprocessing pool's feeder thread can
      stream paths to workers without materialising the whole tree.
    """
    seen: set[Path] = set()

    def _on_error(exc: OSError) -> None:
        print(f"warning: {exc}", file=sys.stderr)

    for root in roots:
        try:
            if root.is_file():
                if root.suffix == ".py":
                    key = root.resolve()
                    if key not in seen:
                        seen.add(key)
                        yield root
            elif root.is_dir():
                for dirpath, dirnames, filenames in root.walk(on_error=_on_error):
                    # Prune well-known irrelevant trees in place.
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for name in filenames:
                        if not name.endswith(".py"):
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
        prog="strip_inline_comments",
        description=(
            "Remove inline (trailing) comments from Python files using libcst. "
            "Files are modified in place. Standalone comments are preserved."
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots: list[Path] = args.paths or [Path.cwd()]

    total_files = 0
    changed_files = 0
    total_removed = 0
    error_count = 0

    # `imap_unordered` streams tasks out and results in as they finish, which
    # keeps memory usage flat and lets us report progress incrementally.
    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            process_file,
            iter_python_files(roots),
            chunksize=CHUNKSIZE,
        )
        for path, removed, error in results:
            total_files += 1
            if error is not None:
                error_count += 1
                print(f"ERROR  {path}: {error}", file=sys.stderr)
            elif removed > 0:
                changed_files += 1
                total_removed += removed
                print(f"{path}: removed {removed} inline comment(s)")

    if total_files == 0:
        print("No Python files found.", file=sys.stderr)
        return 1

    summary = (
        f"\nProcessed {total_files} file(s): "
        f"{changed_files} changed, "
        f"{total_removed} inline comment(s) removed, "
        f"{error_count} error(s)."
    )
    print(summary, file=sys.stderr if error_count else sys.stdout)

    return 2 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
