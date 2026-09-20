#!/data/data/com.termux/files/home/.local/bin/python
"""
pyescape_tool.py — unified Python invalid-escape / regex-literal repair toolkit.

This single script merges the behaviour of:

    find_and_fix_escape_sequence.py
    fix_escape.py
    fix_escape2.py
    fix_re.py
    fix_regex_escape.py
    fix_warning.py
    fixescape.py
    fixre.py
    fregex.py
    gfixre.py

Usage examples
--------------

# Scan current directory for invalid string escape sequences
python pyescape_tool.py escapes

# Fix them by adding raw-string prefixes
python pyescape_tool.py escapes --auto-fix

# Fix them by globally double-escaping invalid backslashes
python pyescape_tool.py escapes --auto-fix --strategy double-backslash

# Scan a specific directory with 8 workers
python pyescape_tool.py escapes src/ tests/ --workers 8

# Double-escape invalid backslashes only (old fixescape.py)
python pyescape_tool.py backslashes --auto-fix

# Convert string literals passed to re.* into raw strings, tokenize mode
python pyescape_tool.py regex --method tokenize --convert add-r --dry-run

# AST mode, line-preserving add-r, with backup
python pyescape_tool.py regex --method ast --convert add-r --backup src/

# AST mode, unicode-escape style (old fix_regex_escape.py)
python pyescape_tool.py regex --method ast --convert unicode-escape

# Extract regex patterns into ./output
python pyescape_tool.py extract --output-dir output

Original -> merged command mapping
----------------------------------

find_and_fix_escape_sequence.py -> python pyescape_tool.py escapes --auto-fix
fix_escape.py                   -> python pyescape_tool.py escapes --auto-fix
fix_escape2.py                  -> python pyescape_tool.py escapes --auto-fix
fix_warning.py                  -> python pyescape_tool.py escapes --auto-fix
fixescape.py                    -> python pyescape_tool.py backslashes --auto-fix
fix_re.py                       -> python pyescape_tool.py regex --method tokenize --convert unescape-double-backslashes --dry-run
fix_regex_escape.py             -> python pyescape_tool.py regex --method ast --convert unicode-escape
fixre.py                        -> python pyescape_tool.py regex --method ast --convert add-r --backup
gfixre.py                       -> python pyescape_tool.py regex --method ast --convert add-r --dry-run
gfixre.py -a                    -> python pyescape_tool.py regex --method ast --convert add-r
fregex.py                       -> python pyescape_tool.py extract --output-dir output

Optional third-party packages
-----------------------------
The original scripts optionally used:
    loguru
    tqdm
This merged script imports them only if available and otherwise falls back to
standard-library behaviour.  No third-party package is required.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import contextlib
import io
import os
import re
import shutil
import sys
import tokenize
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Optional third-party imports (originals used them; we degrade gracefully)
# ---------------------------------------------------------------------------

try:
    from loguru import logger as _loguru_logger
except ImportError:  # pragma: no cover
    _loguru_logger = None

try:
    from tqdm import tqdm as _tqdm
except ImportError:  # pragma: no cover
    _tqdm = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SKIP_DIRS: Final[set[str]] = {
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    ".tox",
    ".pytest_cache",
}

DEFAULT_RE_FUNCTIONS: Final[set[str]] = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "split",
    "findall",
    "finditer",
    "sub",
    "subn",
}

# Used by the old fixescape.py
INVALID_BACKSLASH_RE = re.compile(r'(?<!\\)\\(?![\\\'"abfnrtvNuUx0-7\n])')

# Used by the old fregex.py
REGEX_PATTERN_RE = re.compile(
    r"re\.(?:compile|search|match|findall|fullmatch|finditer)\s*"
    r"\(\s*([rR]?[\"'])(.*?)(?<!\\)\1",
    re.DOTALL,
)

# Matches a Python string literal, including prefixes and triple quotes.
STRING_LITERAL_RE = re.compile(
    r"^([rubfRUBF]*)(\"\"\"|\'\'\'|\"|\')(.*)(\2)$",
    re.DOTALL,
)

TOKEN_IGNORE_TYPES: Final[set[int]] = {
    tokenize.NL,
    tokenize.COMMENT,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    getattr(tokenize, "TYPE_COMMENT", -1),
    tokenize.ERRORTOKEN,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Modification:
    """A single source-code replacement."""

    start: tuple[int, int]
    end: tuple[int, int]
    original: str
    modified: str


@dataclass
class FileResult:
    """Generic per-file result container."""

    path: Path
    status: str = "unchanged"
    message: str = ""
    has_issues: bool = False
    fixed: bool = False
    messages: list[str] = field(default_factory=list)
    changes: int = 0
    diff: str = ""


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def log_debug(message: str) -> None:
    """Log a debug message using loguru when available, otherwise silently."""
    if _loguru_logger is not None:
        _loguru_logger.debug(message)


def log_error(message: str) -> None:
    """Log an error using loguru when available, otherwise print to stderr."""
    if _loguru_logger is not None:
        _loguru_logger.error(message)
    else:
        print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------


def iter_py_files(
    paths: Sequence[str | Path],
    *,
    include_symlinks: bool = False,
    skip_dirs: set[str] | None = None,
    exclude_self: bool = True,
) -> list[Path]:
    """
    Return a sorted list of Python files under *paths*.

    If *paths* is empty, the current directory is used.
    """
    if not paths:
        paths = [Path.cwd()]

    skip_dirs = skip_dirs if skip_dirs is not None else DEFAULT_SKIP_DIRS
    self_path = Path(__file__).resolve() if exclude_self else None
    found: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path).resolve()
        if not path.exists():
            continue

        if path.is_file():
            if path.suffix == ".py" and (self_path is None or path != self_path):
                found.add(path)
            continue

        if not path.is_dir():
            continue

        for root, dirs, files in os.walk(path, followlinks=include_symlinks):
            root_path = Path(root)

            # Prune skipped and optionally symlinked directories.
            dirs[:] = [
                d
                for d in dirs
                if d not in skip_dirs
                and (include_symlinks or not (root_path / d).is_symlink())
            ]

            for name in files:
                if not name.endswith(".py"):
                    continue
                file_path = root_path / name
                if not include_symlinks and file_path.is_symlink():
                    continue
                if self_path is not None and file_path.resolve() == self_path:
                    continue
                found.add(file_path.resolve())

    return sorted(found)


# ---------------------------------------------------------------------------
# String literal helpers
# ---------------------------------------------------------------------------


def parse_string_literal(literal: str) -> tuple[str, str, str] | None:
    """
    Parse a Python string literal into ``(prefix, quote, body)``.

    Returns ``None`` if *literal* is not recognised.
    """
    match = STRING_LITERAL_RE.match(literal)
    if not match:
        return None
    prefix, quote, body = match.group(1), match.group(2), match.group(3)
    return prefix, quote, body


def add_raw_prefix(prefix: str) -> str:
    """
    Add an ``r`` prefix to a string prefix if not already present.

    ``u`` is dropped because ``ur`` is invalid in Python 3.
    """
    if "r" in prefix.lower():
        return prefix
    cleaned = "".join(ch for ch in prefix if ch.lower() != "u")
    return "r" + cleaned


def convert_string_literal(literal: str, mode: str) -> str:
    """
    Convert a string literal according to *mode*.

    Modes:
        add-r
            Add an ``r`` prefix.
        unescape-double-backslashes
            Replace ``\\\\`` with ``\\`` and add an ``r`` prefix.
    """
    parsed = parse_string_literal(literal)
    if parsed is None:
        return literal

    prefix, quote, body = parsed
    if "r" in prefix.lower():
        return literal
    if "\\" not in body:
        return literal

    if mode == "add-r":
        new_prefix = add_raw_prefix(prefix)
        return f"{new_prefix}{quote}{body}{quote}"

    if mode == "unescape-double-backslashes":
        new_body = body.replace("\\\\", "\\")
        new_prefix = add_raw_prefix(prefix)
        return f"{new_prefix}{quote}{new_body}{quote}"

    return literal


def literal_has_invalid_escape(literal: str) -> bool:
    """
    Return True if compiling ``x = literal`` emits an invalid-escape warning.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(f"x = {literal}", "<string>", "exec")
        except SyntaxError:
            return False

        for warning in caught:
            if issubclass(
                warning.category, SyntaxWarning
            ) and "invalid escape sequence" in str(warning.message):
                return True
    return False


# ---------------------------------------------------------------------------
# Source modification helper
# ---------------------------------------------------------------------------


def apply_modifications(source: str, modifications: Iterable[Modification]) -> str:
    """
    Apply *modifications* to *source*.

    Modifications are applied from the end of the file backwards so that earlier
    offsets remain valid.
    """
    mods = list(modifications)
    if not mods:
        return source

    lines = source.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))

    def absolute_offset(pos: tuple[int, int]) -> int:
        line_no, col = pos
        return line_starts[line_no - 1] + col

    result = source
    for mod in sorted(
        mods,
        key=lambda m: (m.start[0], m.start[1]),
        reverse=True,
    ):
        start = absolute_offset(mod.start)
        end = absolute_offset(mod.end)
        result = result[:start] + mod.modified + result[end:]

    return result


# ---------------------------------------------------------------------------
# Invalid escape scanning / fixing
# ---------------------------------------------------------------------------


def check_invalid_escapes_bytes(data: bytes, filename: str) -> tuple[bool, list[str]]:
    """
    Compile *data* and return ``(has_issues, messages)`` for invalid escapes.
    """
    messages: list[str] = []
    has_issues = False

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(data, filename, "exec")
        except SyntaxError as exc:
            if "invalid escape sequence" in str(exc):
                has_issues = True
                messages.append(f"Line {exc.lineno}: SyntaxError: {exc.msg}")
        for warning in caught:
            if issubclass(
                warning.category, SyntaxWarning
            ) and "invalid escape sequence" in str(warning.message):
                has_issues = True
                line = getattr(warning, "lineno", "Unknown")
                messages.append(f"Line {line}: SyntaxWarning: {warning.message}")

    return has_issues, messages


def tokenize_fix_invalid_escapes(path: Path) -> bool:
    """
    Add raw-string prefixes to string literals with invalid escapes.

    This is the tokenize-based strategy used by several original scripts.
    """
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
            encoding = handle.encoding
    except Exception:
        return False

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return False

    mods: list[Modification] = []
    for tok in tokens:
        if tok.type != tokenize.STRING:
            continue
        if not literal_has_invalid_escape(tok.string):
            continue

        new_literal = convert_string_literal(tok.string, "add-r")
        if new_literal != tok.string:
            mods.append(
                Modification(
                    start=tok.start,
                    end=tok.end,
                    original=tok.string,
                    modified=new_literal,
                )
            )

    if not mods:
        return False

    new_source = apply_modifications(source, mods)
    try:
        ast.parse(new_source)
    except SyntaxError:
        return False

    path.write_text(new_source, encoding=encoding)
    return True


def double_escape_file(path: Path, *, auto_fix: bool) -> tuple[int, bool]:
    """
    Count invalid backslashes in *path* and optionally double-escape them.

    Returns ``(count, fixed)``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0, False

    matches = list(INVALID_BACKSLASH_RE.finditer(text))
    count = len(matches)

    if count == 0 or not auto_fix:
        return count, False

    new_text = INVALID_BACKSLASH_RE.sub(r"\\\\", text)
    try:
        path.write_text(new_text, encoding="utf-8")
    except Exception:
        return count, False

    return count, True


def process_escapes_file(
    path: Path,
    *,
    auto_fix: bool,
    strategy: str,
) -> FileResult:
    """Process one file for invalid string escape sequences."""
    result = FileResult(path=path)

    try:
        data = path.read_bytes()
    except Exception as exc:
        result.messages.append(f"Could not read file: {exc}")
        return result

    has_issues, messages = check_invalid_escapes_bytes(data, str(path))
    result.has_issues = has_issues
    result.messages = messages

    if not has_issues or not auto_fix:
        return result

    if strategy == "r-prefix":
        result.fixed = tokenize_fix_invalid_escapes(path)
    elif strategy == "double-backslash":
        count, fixed = double_escape_file(path, auto_fix=True)
        result.fixed = fixed
        if fixed:
            result.messages.append(f"Double-escaped {count} invalid backslash(es)")
    else:
        result.messages.append(f"Unknown strategy: {strategy}")

    return result


def process_backslashes_file(path: Path, *, auto_fix: bool) -> FileResult:
    """Process one file using the global invalid-backslash regex."""
    result = FileResult(path=path)

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        result.messages.append(f"Error reading file: {exc}")
        return result

    matches = list(INVALID_BACKSLASH_RE.finditer(text))
    result.changes = len(matches)

    if result.changes == 0:
        return result

    result.has_issues = True
    result.messages.append(f"{result.changes} invalid escape sequence(s)")

    if auto_fix:
        new_text = INVALID_BACKSLASH_RE.sub(r"\\\\", text)
        try:
            path.write_text(new_text, encoding="utf-8")
            result.fixed = True
            result.status = "fixed"
        except Exception as exc:
            result.messages.append(f"Failed to write: {exc}")

    return result


# ---------------------------------------------------------------------------
# Regex-literal conversion
# ---------------------------------------------------------------------------


def find_tokenize_regex_modifications(
    source: str,
    *,
    convert_mode: str,
    functions: set[str],
) -> list[Modification]:
    """
    Find ``re.func("...")`` calls via tokenize and return replacements.
    """
    modifications: list[Modification] = []

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return modifications

    for i, tok in enumerate(tokens):
        if tok.type != tokenize.NAME or tok.string != "re":
            continue
        if i + 4 >= len(tokens):
            continue

        dot = tokens[i + 1]
        func = tokens[i + 2]
        paren = tokens[i + 3]
        string_tok = tokens[i + 4]

        if (
            dot.type == tokenize.OP
            and dot.string == "."
            and func.type == tokenize.NAME
            and func.string in functions
            and paren.type == tokenize.OP
            and paren.string == "("
            and string_tok.type == tokenize.STRING
        ):
            new_literal = convert_string_literal(string_tok.string, convert_mode)
            if new_literal != string_tok.string:
                modifications.append(
                    Modification(
                        start=string_tok.start,
                        end=string_tok.end,
                        original=string_tok.string,
                        modified=new_literal,
                    )
                )

    return modifications


def find_ast_regex_modifications(
    source: str,
    *,
    functions: set[str],
) -> list[Modification]:
    """
    Find ``re.func("...")`` calls via AST and return line-preserving replacements.
    """
    modifications: list[Modification] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return modifications

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
            and node.func.attr in functions
            and node.args
        ):
            continue

        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue

        literal = ast.get_source_segment(source, arg)
        if literal is None:
            continue

        new_literal = convert_string_literal(literal, "add-r")
        if new_literal == literal:
            continue

        modifications.append(
            Modification(
                start=(arg.lineno, arg.col_offset),
                end=(arg.end_lineno, arg.end_col_offset),
                original=literal,
                modified=new_literal,
            )
        )

    return modifications


def ast_unicode_escape_regex(
    source: str,
    *,
    functions: set[str],
) -> tuple[str, int]:
    """
    AST-based unicode-escape conversion, equivalent to fix_regex_escape.py.

    Returns ``(new_source, changes)``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, 0

    changes = 0

    class Transformer(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.Call:
            nonlocal changes
            self.generic_visit(node)

            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr in functions
                and node.args
            ):
                return node

            arg = node.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                return node

            old = arg.value
            new = old.encode("unicode_escape").decode("ascii")
            new = new.replace("\\\\n", "\\n")
            new = new.replace("\\\\t", "\\t")
            new = new.replace("\\\\r", "\\r")

            if new != old:
                arg.value = new
                changes += 1

            return node

    transformer = Transformer()
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree), changes


def process_regex_file(
    path: Path,
    *,
    method: str,
    convert: str,
    dry_run: bool,
    backup: bool,
    backup_suffix: str,
    functions: set[str],
) -> FileResult:
    """Process one file for ``re.*`` string-literal conversion."""
    result = FileResult(path=path)

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        result.status = "error"
        result.message = f"Failed to read: {exc}"
        return result

    if "re." not in source:
        result.message = "No re calls found"
        return result

    if method == "tokenize":
        mods = find_tokenize_regex_modifications(
            source,
            convert_mode=convert,
            functions=functions,
        )
        if not mods:
            result.message = "No changes needed"
            return result
        new_source = apply_modifications(source, mods)
        changes = len(mods)

    elif method == "ast":
        if convert == "unicode-escape":
            new_source, changes = ast_unicode_escape_regex(
                source,
                functions=functions,
            )
        else:
            mods = find_ast_regex_modifications(
                source,
                functions=functions,
            )
            if not mods:
                result.message = "No changes needed"
                return result
            new_source = apply_modifications(source, mods)
            changes = len(mods)

    else:
        result.status = "error"
        result.message = f"Unknown method: {method}"
        return result

    if changes == 0:
        result.message = "No changes needed"
        return result

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        result.status = "error"
        result.message = f"Validation failed - syntax error after conversion: {exc}"
        return result

    result.changes = changes

    if dry_run:
        diff = unified_diff(
            source.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
        result.status = "would_modify"
        result.message = f"Would modify {changes} string(s)"
        result.diff = "".join(diff)
        return result

    if backup:
        backup_path = path.with_suffix(path.suffix + backup_suffix)
        try:
            shutil.copy2(path, backup_path)
        except Exception as exc:
            result.status = "error"
            result.message = f"Failed to create backup: {exc}"
            return result

    try:
        path.write_text(new_source, encoding="utf-8")
    except Exception as exc:
        result.status = "error"
        result.message = f"Failed to write: {exc}"
        return result

    result.status = "modified"
    result.message = f"Modified {changes} string(s)"
    return result


# ---------------------------------------------------------------------------
# Regex extraction
# ---------------------------------------------------------------------------


def extract_regex_from_file(path: Path, output_dir: Path) -> tuple[Path, int]:
    """Extract regex patterns from one file and write them to *output_dir*."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return path, 0

    patterns = REGEX_PATTERN_RE.findall(text)
    if not patterns:
        return path, 0

    try:
        relative = path.relative_to(Path.cwd())
    except ValueError:
        relative = path

    out_name = str(relative).replace(os.sep, "_") + ".txt"
    out_path = output_dir / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(patterns), encoding="utf-8")
    return path, len(patterns)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


def _parse_skip_dirs(raw: str) -> set[str]:
    """Parse a comma-separated skip-dir list."""
    if not raw.strip():
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _parse_functions(raw: str) -> set[str]:
    """Parse a comma-separated ``re`` function list."""
    return {part.strip() for part in raw.split(",") if part.strip()}


def cmd_escapes(args: argparse.Namespace) -> int:
    """Implement the ``escapes`` subcommand."""
    skip_dirs = _parse_skip_dirs(args.skip_dirs)
    files = iter_py_files(
        args.paths,
        include_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Scanning {len(files)} Python files...")
        if args.auto_fix:
            print(f"Auto-fix enabled (strategy: {args.strategy})")

    results: list[FileResult] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_escapes_file,
                path,
                auto_fix=args.auto_fix,
                strategy=args.strategy,
            ): path
            for path in files
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    issue_count = 0
    fixed_count = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if not result.has_issues:
            continue
        issue_count += 1
        status = "FIXED" if result.fixed else "WARNING"
        if not args.quiet:
            print(f"[{status}] {result.path}")
            for message in result.messages:
                print(f"   -> {message}")
            print()
        if result.fixed:
            fixed_count += 1

    if not args.quiet:
        print("-" * 40)
        print("Scan Complete.")
        print(f"Files with issues: {issue_count}")
        if args.auto_fix:
            print(f"Files successfully fixed: {fixed_count}")

    return 0


def cmd_backslashes(args: argparse.Namespace) -> int:
    """Implement the ``backslashes`` subcommand."""
    skip_dirs = _parse_skip_dirs(args.skip_dirs)
    files = iter_py_files(
        args.paths,
        include_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Scanning {len(files)} Python files...")

    results: list[FileResult] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_backslashes_file, path, auto_fix=args.auto_fix): path
            for path in files
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    issue_files = 0
    total_issues = 0
    fixed_files = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if result.changes == 0:
            continue
        issue_files += 1
        total_issues += result.changes
        status = "FIXED" if result.fixed else "FOUND"
        if not args.quiet:
            print(
                f"[{status}] {result.path}: {result.changes} invalid escape sequence(s)"
            )
        if result.fixed:
            fixed_files += 1

    if not args.quiet:
        print("\n--- Summary ---")
        print(f"Files scanned: {len(files)}")
        print(f"Files with issues: {issue_files}")
        print(f"Total issues: {total_issues}")
        if args.auto_fix:
            print(f"Files fixed: {fixed_files}")

    return 1 if issue_files and not args.auto_fix else 0


def cmd_regex(args: argparse.Namespace) -> int:
    """Implement the ``regex`` subcommand."""
    if args.method == "tokenize" and args.convert == "unicode-escape":
        print("Error: --convert unicode-escape requires --method ast.", file=sys.stderr)
        return 2

    skip_dirs = _parse_skip_dirs(args.skip_dirs)
    functions = _parse_functions(args.functions)
    files = iter_py_files(
        args.paths,
        include_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Found {len(files)} Python files")
        print(f"Method: {args.method}, convert: {args.convert}")
        print(f"Workers: {args.workers}")
        if args.dry_run:
            print("DRY RUN - no files will be modified")
        if args.backup:
            print(f"Backup suffix: {args.backup_suffix}")

    results: list[FileResult] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_regex_file,
                path,
                method=args.method,
                convert=args.convert,
                dry_run=args.dry_run,
                backup=args.backup,
                backup_suffix=args.backup_suffix,
                functions=functions,
            ): path
            for path in files
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    modified = 0
    errors = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if result.status == "error":
            errors += 1
            log_error(f"ERROR {result.path}: {result.message}")
        elif result.status == "modified":
            modified += 1
            if not args.quiet:
                print(f"FIXED {result.path}: {result.message}")
        elif result.status == "would_modify":
            modified += 1
            if not args.quiet:
                print(f"WOULD MODIFY {result.path}: {result.message}")
                if args.verbose and result.diff:
                    print(result.diff)
        elif args.verbose and result.status == "unchanged":
            print(f"UNCHANGED {result.path}: {result.message}")

    if not args.quiet:
        print("-" * 40)
        print("Summary:")
        print(f"  Total files: {len(files)}")
        print(f"  Modified/would modify: {modified}")
        print(f"  Errors: {errors}")

    return 1 if errors else 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Implement the ``extract`` subcommand."""
    skip_dirs = _parse_skip_dirs(args.skip_dirs)
    files = iter_py_files(
        args.paths,
        include_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print(f"Extracting regex patterns from {len(files)} files into {output_dir}")

    progress = None
    if _tqdm is not None and not args.quiet:
        progress = _tqdm(total=len(files), desc="Progress", unit="file")

    processed = 0
    total_patterns = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(extract_regex_from_file, path, output_dir): path
            for path in files
        }
        for future in concurrent.futures.as_completed(futures):
            path, count = future.result()
            processed += 1
            total_patterns += count
            if progress is not None:
                progress.update(1)
            if count and not args.quiet:
                print(f"Processed {path} with {count} regex patterns.")

    if progress is not None:
        progress.close()

    if not args.quiet:
        print(f"Scanning complete. Processed {processed} files.")
        print(f"Total regex patterns extracted: {total_patterns}")

    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the full CLI parser."""
    parser = argparse.ArgumentParser(
        prog="pyescape_tool.py",
        description="Find/fix invalid Python escape sequences and regex literals.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current directory).",
    )
    common.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="Number of worker processes/threads (default: min(8, CPU count)).",
    )
    common.add_argument(
        "--include-symlinks",
        action="store_true",
        help="Follow symlinked directories and include symlinked files.",
    )
    common.add_argument(
        "--skip-dirs",
        default=",".join(sorted(DEFAULT_SKIP_DIRS)),
        help="Comma-separated directory names to skip.",
    )
    common.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress non-error output.",
    )
    common.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output.",
    )

    # escapes
    p_esc = subparsers.add_parser(
        "escapes",
        parents=[common],
        help="Find/fix invalid string escape sequences.",
    )
    p_esc.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Apply fixes automatically.",
    )
    p_esc.add_argument(
        "--strategy",
        choices=["r-prefix", "double-backslash"],
        default="r-prefix",
        help="Fix strategy (default: r-prefix).",
    )
    p_esc.set_defaults(func=cmd_escapes)

    # backslashes
    p_back = subparsers.add_parser(
        "backslashes",
        parents=[common],
        help="Double-escape invalid backslashes globally.",
    )
    p_back.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Apply fixes automatically.",
    )
    p_back.set_defaults(func=cmd_backslashes)

    # regex
    p_re = subparsers.add_parser(
        "regex",
        parents=[common],
        help="Convert string literals passed to re.* functions.",
    )
    p_re.add_argument(
        "--method",
        choices=["tokenize", "ast"],
        default="tokenize",
        help="Detection method (default: tokenize).",
    )
    p_re.add_argument(
        "--convert",
        choices=["add-r", "unescape-double-backslashes", "unicode-escape"],
        default="add-r",
        help="Conversion mode (default: add-r).",
    )
    p_re.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without writing files.",
    )
    p_re.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup before writing.",
    )
    p_re.add_argument(
        "--backup-suffix",
        default=".bak",
        help="Backup suffix (default: .bak).",
    )
    p_re.add_argument(
        "--functions",
        default=",".join(sorted(DEFAULT_RE_FUNCTIONS)),
        help="Comma-separated re.* function names to process.",
    )
    p_re.set_defaults(func=cmd_regex)

    # extract
    p_ext = subparsers.add_parser(
        "extract",
        parents=[common],
        help="Extract regex patterns from re.* calls.",
    )
    p_ext.add_argument(
        "--output-dir",
        "-o",
        default="output",
        help="Output directory (default: output).",
    )
    p_ext.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Thread workers for extraction (default: 8).",
    )
    p_ext.set_defaults(func=cmd_extract)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
