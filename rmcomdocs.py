#!/data/data/com.termux/files/home/.local/bin/python
"""
rmcomdocs.py — unified comments/docstrings stripper for Python source trees.

This single script merges the behaviour of four earlier tools
(gemc.py, t5.py, grmc_ts.py, tsrmc.py) behind one argparse CLI.

Subcommands
-----------
strip     Remove comments (and optionally docstrings) from Python files.
compare   Dry-run comparison between the tree-sitter and AST engines.

Original script -> equivalent command
-------------------------------------
gemc.py       ->  python rmcomdocs.py strip . --engine query  --docstring pass \\
                          --workers 4
t5.py         ->  python rmcomdocs.py strip . --engine query  --docstring pass \\
                          --eat-trailing-newline --remove-blank-lines \\
                          --keep-todo --workers 4
grmc_ts.py    ->  python rmcomdocs.py strip . --engine cursor --docstring pass \\
                          --keep-module-docstring --workers 8
tsrmc.py      ->  python rmcomdocs.py strip . --engine query  --preserve-lines \\
                          --workers 8
tsrmc.py --compare -> python rmcomdocs.py compare . --workers 8

Third-party dependencies
------------------------
    tree-sitter
    tree-sitter-python
"""

from __future__ import annotations

import argparse
import ast
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Third-party imports (guarded)
# ---------------------------------------------------------------------------
try:
    import tree_sitter_python as _tspython
    from tree_sitter import Language, Node, Parser, Query, QueryCursor
except ImportError as _exc:  # pragma: no cover
    print(
        f"error: missing dependency ({_exc}); "
        "install with: pip install tree-sitter tree-sitter-python",
        file=sys.stderr,
    )
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Constants (configurable via CLI where sensible)
# ---------------------------------------------------------------------------

_LANGUAGE = Language(_tspython.language())

# Query mirroring gemc.py / t5.py.
_DOCSTRING_QUERY = """
(comment) @comment
(block
  . (expression_statement
    (string)) @docstring)
(module
  . (expression_statement
    (string)) @docstring)
"""

# Prefixes preserved by every original script.
_BASE_KEEP_PREFIXES: tuple[str, ...] = ("#!", "# type:", "# fmt:")
# Extra prefixes preserved by t5.py.
_TODO_KEEP_PREFIXES: tuple[str, ...] = ("# TODO", "# noqa")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StripConfig:
    """All knobs that control the rewrite (parallel-safe / picklable)."""

    engine: str = "query"  # "query" | "cursor" | "ast"
    docstring_action: str = "pass"  # "pass" | "remove"
    preserve_lines: bool = False  # blank out instead of splice
    eat_trailing_newline: bool = False  # t5.py behaviour
    remove_blank_lines: bool = False  # t5.py behaviour
    keep_module_docstring: bool = False  # grmc_ts.py behaviour
    keep_prefixes: tuple[str, ...] = _BASE_KEEP_PREFIXES


@dataclass
class Edit:
    """A single byte-range replacement inside a file."""

    start: int
    end: int
    replacement: bytes


@dataclass
class FileResult:
    """Outcome of processing one file (picklable)."""

    path: Path
    success: bool
    error: str = ""
    comments_removed: int = 0
    docstrings_removed: int = 0
    original_size: int = 0
    new_size: int = 0
    elapsed: float = 0.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _make_parser() -> Parser:
    """Create a fresh tree-sitter parser bound to the Python grammar."""
    return Parser(_LANGUAGE)


def _comment_is_kept(text: str, keep_prefixes: Sequence[str]) -> bool:
    """Return True if the comment should be preserved."""
    stripped = text.strip()
    return any(stripped.startswith(prefix) for prefix in keep_prefixes)


def _eat_trailing_newlines(source: bytes, edits: list[Edit]) -> None:
    """Extend an edit's end to swallow a single trailing '\\n' (t5.py)."""
    for edit in edits:
        if edit.end < len(source) and source[edit.end : edit.end + 1] == b"\n":
            edit.end += 1


def _remove_blank_lines(text: str) -> str:
    """Collapse runs of blank lines into a single blank line (t5.py)."""
    out: list[str] = []
    prev_blank = False
    for line in text.split("\n"):
        blank = not line.strip()
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Engine A: tree-sitter *query* (gemc.py / t5.py / tsrmc.py semantics)
# ---------------------------------------------------------------------------


def _edits_via_query(source: bytes, cfg: StripConfig) -> tuple[list[Edit], int, int]:
    """Collect (comments, docstrings) edits using a tree-sitter query."""
    parser = _make_parser()
    tree = parser.parse(source)
    query = Query(_LANGUAGE, _DOCSTRING_QUERY)
    cursor = QueryCursor(query)
    captures = cursor.captures(tree.root_node)

    seen: set[tuple[int, int]] = set()
    edits: list[Edit] = []
    n_comments = n_docstrings = 0

    for node, tag in captures:
        key = (node.start_byte, node.end_byte)
        if key in seen:
            continue
        seen.add(key)

        if tag == "comment":
            text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
            if _comment_is_kept(text, cfg.keep_prefixes):
                continue
            edits.append(Edit(node.start_byte, node.end_byte, b""))
            n_comments += 1

        elif tag == "docstring":
            parent = node.parent
            grandparent = parent.parent if parent is not None else None
            is_module_doc = grandparent is not None and grandparent.type == "module"
            if is_module_doc and cfg.keep_module_docstring:
                continue

            if (
                cfg.docstring_action == "pass"
                and parent is not None
                and parent.named_child_count == 1
            ):
                edits.append(Edit(node.start_byte, node.end_byte, b"pass"))
            else:
                edits.append(Edit(node.start_byte, node.end_byte, b""))
            n_docstrings += 1

    return edits, n_comments, n_docstrings


# ---------------------------------------------------------------------------
# Engine B: tree-sitter *cursor walk* (grmc_ts.py semantics)
# ---------------------------------------------------------------------------


def _edits_via_cursor(source: bytes, cfg: StripConfig) -> tuple[list[Edit], int, int]:
    """Collect edits by manually walking the tree-sitter tree."""
    parser = _make_parser()
    tree = parser.parse(source)
    root = tree.root_node

    # Detect a module-level docstring (first statement is a bare string).
    module_doc: Node | None = None
    if root.child_count > 0:
        first = root.child(0)
        if first is not None and first.type == "expression_statement":
            inner = first.child(0)
            if inner is not None and inner.type == "string":
                module_doc = first

    edits: list[Edit] = []
    n_comments = n_docstrings = 0

    walker = tree.walk()
    done = False
    while not done:
        node = walker.node

        if node.type == "comment":
            text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
            if not _comment_is_kept(text, cfg.keep_prefixes):
                edits.append(Edit(node.start_byte, node.end_byte, b""))
                n_comments += 1

        elif node.type == "expression_statement" and node != module_doc:
            inner = node.child(0)
            if inner is not None and inner.type == "string":
                parent = node.parent
                if parent is not None and parent.type == "block":
                    if cfg.docstring_action == "pass" and parent.named_child_count == 1:
                        edits.append(Edit(node.start_byte, node.end_byte, b"pass"))
                    else:
                        edits.append(Edit(node.start_byte, node.end_byte, b""))
                    n_docstrings += 1

        # DFS
        if walker.goto_first_child():
            continue
        if walker.goto_next_sibling():
            continue
        while True:
            if not walker.goto_parent():
                done = True
                break
            if walker.goto_next_sibling():
                break

    # Handle module docstring if asked to remove it.
    if module_doc is not None and not cfg.keep_module_docstring:
        if cfg.docstring_action == "pass" and root.named_child_count == 1:
            edits.append(Edit(module_doc.start_byte, module_doc.end_byte, b"pass"))
        else:
            edits.append(Edit(module_doc.start_byte, module_doc.end_byte, b""))
        n_docstrings += 1

    return edits, n_comments, n_docstrings


# ---------------------------------------------------------------------------
# Engine C: line-based AST/comment stripper (tsrmc.py AST fallback)
# ---------------------------------------------------------------------------


def _strip_line_comment(line: str) -> str:
    """Remove the first '#' comment from a single source line."""
    in_string = False
    quote_char: str | None = None
    out: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in ("'", '"') and (i == 0 or line[i - 1] != "\\"):
            if not in_string:
                in_string = True
                quote_char = ch
            elif ch == quote_char:
                in_string = False
                quote_char = None
            out.append(ch)
        elif ch == "#" and not in_string:
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _strip_via_ast_line(source: bytes) -> bytes:
    """Whole-file line-based strip (used by tsrmc.py's AST path)."""
    text = source.decode("utf-8", "replace")
    stripped = "\n".join(_strip_line_comment(line) for line in text.split("\n"))
    return stripped.encode("utf-8")


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------


def _apply_edits(source: bytes, edits: Iterable[Edit], cfg: StripConfig) -> bytes:
    """Apply edits either by splicing or by blanking (preserve-lines)."""
    edits = sorted(edits, key=lambda e: e.start)
    if not edits:
        return source

    if cfg.preserve_lines:
        buf = bytearray(source)
        for edit in edits:
            chunk = source[edit.start : edit.end]
            newlines = chunk.count(b"\n")
            if newlines:
                buf[edit.start : edit.end] = b"\n" * newlines
            else:
                buf[edit.start : edit.end] = b" " * (edit.end - edit.start)
        return bytes(buf)

    # Splice mode: rebuild the byte string front-to-back.
    out = bytearray()
    cursor = 0
    for edit in edits:
        out.extend(source[cursor : edit.start])
        out.extend(edit.replacement)
        cursor = edit.end
    out.extend(source[cursor:])
    return bytes(out)


# ---------------------------------------------------------------------------
# Per-file worker
# ---------------------------------------------------------------------------


def _process_file(path: Path, cfg: StripConfig, write: bool = True) -> FileResult:
    """Strip a single file, validate, and (optionally) write it back."""
    t0 = time.perf_counter()
    try:
        source = path.read_bytes()
    except OSError as exc:
        return FileResult(
            path=path,
            success=False,
            error=f"read failed: {exc}",
            elapsed=time.perf_counter() - t0,
        )

    original_size = len(source)
    n_comments = n_docstrings = 0

    try:
        if cfg.engine in ("query", "cursor"):
            if cfg.engine == "query":
                edits, n_comments, n_docstrings = _edits_via_query(source, cfg)
            else:
                edits, n_comments, n_docstrings = _edits_via_cursor(source, cfg)

            if cfg.eat_trailing_newline:
                _eat_trailing_newlines(source, edits)

            new_source = _apply_edits(source, edits, cfg)

            if cfg.remove_blank_lines:
                new_source = _remove_blank_lines(
                    new_source.decode("utf-8", "replace")
                ).encode("utf-8")

        elif cfg.engine == "ast":
            new_source = _strip_via_ast_line(source)

        else:
            raise ValueError(f"unknown engine: {cfg.engine!r}")

    except Exception as exc:  # noqa: BLE001 — per-file robustness
        return FileResult(
            path=path, success=False, error=str(exc), elapsed=time.perf_counter() - t0
        )

    if new_source == source:
        return FileResult(
            path=path,
            success=True,
            error="no changes",
            original_size=original_size,
            new_size=original_size,
            elapsed=time.perf_counter() - t0,
        )

    # Safety net: reject any change that breaks the AST.
    try:
        ast.parse(new_source, filename=str(path))
    except SyntaxError as exc:
        return FileResult(
            path=path,
            success=False,
            error=f"syntax validation failed: {exc}",
            comments_removed=n_comments,
            docstrings_removed=n_docstrings,
            original_size=original_size,
            elapsed=time.perf_counter() - t0,
        )

    if write:
        try:
            path.write_bytes(new_source)
        except OSError as exc:
            return FileResult(
                path=path,
                success=False,
                error=f"write failed: {exc}",
                elapsed=time.perf_counter() - t0,
            )

    return FileResult(
        path=path,
        success=True,
        comments_removed=n_comments,
        docstrings_removed=n_docstrings,
        original_size=original_size,
        new_size=len(new_source),
        elapsed=time.perf_counter() - t0,
    )


# ---------------------------------------------------------------------------
# File discovery / summary helpers
# ---------------------------------------------------------------------------


def _discover_python_files(paths: Sequence[str]) -> list[Path]:
    """Turn a mix of files and directories into a sorted list of .py files."""
    if not paths:
        paths = ["."]
    found: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py":
            found.add(p)
        elif p.is_dir():
            found.update(p.rglob("*.py"))
    return sorted(found)


def _parallel_map(
    files: list[Path], cfg: StripConfig, write: bool, workers: int
) -> list[FileResult]:
    """Run _process_file over files, in-process or via a spawn pool."""
    if workers <= 1 or len(files) <= 1:
        return [_process_file(f, cfg, write) for f in files]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=workers) as pool:
        # starmap keeps ordering stable for pretty per-file reporting.
        return pool.starmap(_process_file, [(f, cfg, write) for f in files])


def _print_summary(results: list[FileResult], label: str, total_time: float) -> None:
    """Print the tsrmc.py-style aggregate report."""
    ok = [r for r in results if r.success and r.error != "no changes"]
    unchanged = [r for r in results if r.success and r.error == "no changes"]
    failed = [r for r in results if not r.success]

    in_size = sum(r.original_size for r in results)
    out_size = sum(r.new_size for r in results)
    saved = max(in_size - out_size, 0)
    pct = (saved / in_size * 100.0) if in_size else 0.0

    print("=" * 52)
    print(f"Results ({label})")
    print("=" * 52)
    print(f"Files total     : {len(results)}")
    print(f"  modified      : {len(ok)}")
    print(f"  unchanged     : {len(unchanged)}")
    print(f"  failed        : {len(failed)}")
    print(f"Total time      : {total_time:.3f}s")
    print(f"Original bytes  : {in_size:,}")
    print(f"New bytes       : {out_size:,}")
    print(f"Reduction       : {saved:,} bytes ({pct:.1f}%)")


# ---------------------------------------------------------------------------
# Subcommand: strip
# ---------------------------------------------------------------------------


def _build_keep_prefixes(args: argparse.Namespace) -> tuple[str, ...]:
    prefixes = list(_BASE_KEEP_PREFIXES)
    if getattr(args, "keep_todo", False):
        prefixes.extend(_TODO_KEEP_PREFIXES)
    if getattr(args, "keep_prefix", None):
        prefixes.extend(args.keep_prefix)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in prefixes:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return tuple(unique)


def cmd_strip(args: argparse.Namespace) -> int:
    cfg = StripConfig(
        engine=args.engine,
        docstring_action=args.docstring,
        preserve_lines=args.preserve_lines,
        eat_trailing_newline=args.eat_trailing_newline,
        remove_blank_lines=args.remove_blank_lines,
        keep_module_docstring=args.keep_module_docstring,
        keep_prefixes=_build_keep_prefixes(args),
    )

    files = _discover_python_files(args.paths)
    if not files:
        print("No Python files found.", file=sys.stderr)
        return 0

    if not args.quiet:
        print(
            f"Processing {len(files)} file(s) "
            f"[engine={cfg.engine}, workers={args.workers}, "
            f"dry_run={args.dry_run}]"
        )

    t0 = time.perf_counter()
    results = _parallel_map(files, cfg, write=not args.dry_run, workers=args.workers)
    elapsed = time.perf_counter() - t0

    failed = 0
    if not args.quiet:
        for r in results:
            if not r.success:
                failed += 1
                print(f"[FAIL]  {r.path}: {r.error}")
            elif r.error == "no changes":
                if args.verbose:
                    print(f"[SKIP]  {r.path}")
            else:
                print(
                    f"[OK]    {r.path}  "
                    f"comments={r.comments_removed} "
                    f"docstrings={r.docstrings_removed}"
                )
        _print_summary(results, cfg.engine, elapsed)

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Subcommand: compare  (tsrmc.py --compare)
# ---------------------------------------------------------------------------


def cmd_compare(args: argparse.Namespace) -> int:
    files = _discover_python_files(args.paths)
    if not files:
        print("No Python files found.", file=sys.stderr)
        return 0

    print(
        f"Comparing engines on {len(files)} file(s) (dry-run, no files will be written)"
    )
    print("=" * 52)

    timings: dict[str, float] = {}
    for engine in ("query", "ast"):
        cfg = StripConfig(
            engine=engine,
            docstring_action="pass",
            preserve_lines=True,  # matches tsrmc.py's blank-out approach
        )
        t0 = time.perf_counter()
        results = _parallel_map(files, cfg, write=False, workers=args.workers)
        dt = time.perf_counter() - t0
        timings[engine] = dt

        ok = sum(1 for r in results if r.success)
        print(f"[{engine:<5}] ok={ok}/{len(results)}  time={dt:.3f}s")

    print("=" * 52)
    print("Performance comparison")
    print("=" * 52)
    ts = timings["query"]
    ast_t = timings["ast"]
    print(f"tree-sitter (query) : {ts:.3f}s")
    print(f"ast (line-based)    : {ast_t:.3f}s")
    speedup = (ast_t / ts) if ts > 0 else 0.0
    print(f"Speedup             : {speedup:.2f}x")
    print("NOTE: no files were modified (dry-run mode).")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rmcomdocs",
        description="Strip comments and docstrings from Python source trees.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- strip -------------------------------------------------------------
    sp = sub.add_parser(
        "strip", help="Rewrite Python files to drop comments/docstrings."
    )
    sp.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to scan (default: current directory).",
    )
    sp.add_argument(
        "--engine",
        choices=("query", "cursor", "ast"),
        default="query",
        help="Traversal strategy (default: query).",
    )
    sp.add_argument(
        "--docstring",
        choices=("pass", "remove"),
        default="pass",
        help="How to handle docstrings: replace with `pass` when "
        "they are the only statement, or remove entirely "
        "(default: pass).",
    )
    sp.add_argument(
        "--preserve-lines",
        action="store_true",
        help="Blank out removed text instead of deleting it, "
        "keeping line numbers intact.",
    )
    sp.add_argument(
        "--eat-trailing-newline",
        action="store_true",
        help="Also consume the newline that follows removed text (t5.py behaviour).",
    )
    sp.add_argument(
        "--remove-blank-lines",
        action="store_true",
        help="Collapse consecutive blank lines after stripping (t5.py behaviour).",
    )
    sp.add_argument(
        "--keep-module-docstring",
        action="store_true",
        help="Preserve the file-level module docstring (grmc_ts.py behaviour).",
    )
    sp.add_argument(
        "--keep-todo",
        action="store_true",
        help="Also preserve '# TODO' and '# noqa' comments (t5.py behaviour).",
    )
    sp.add_argument(
        "--keep-prefix",
        action="append",
        default=None,
        metavar="PREFIX",
        help="Extra comment prefix to preserve (repeatable).",
    )
    sp.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of worker processes (default: CPU count).",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report, but do not write files.",
    )
    sp.add_argument(
        "--quiet", action="store_true", help="Suppress per-file and summary output."
    )
    sp.add_argument(
        "-v", "--verbose", action="store_true", help="Also report unchanged files."
    )
    sp.set_defaults(func=cmd_strip)

    # --- compare -----------------------------------------------------------
    cp = sub.add_parser("compare", help="Dry-run: compare tree-sitter vs AST engines.")
    cp.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to scan (default: current directory).",
    )
    cp.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of worker processes (default: CPU count).",
    )
    cp.set_defaults(func=cmd_compare)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
