#!/data/data/com.termux/files/home/.local/bin/python
"""
pyescape_tool.py

Find and fix invalid Python escape sequences and regex string literals.

Subcommands:
    escapes      - Find/fix invalid string escape sequences.
    backslashes  - Double-escape invalid backslashes globally.
    regex        - Convert string literals passed to re.* functions.
    extract      - Extract regex patterns from re.* calls.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import pathlib
import re
import shutil
import sys
import tokenize
import warnings
from concurrent import futures
from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# Optional third-party dependencies
# ---------------------------------------------------------------------------

try:
    from loguru import logger as _loguru_logger
except ImportError:
    _loguru_logger = None

try:
    from tqdm import tqdm as _tqdm
except ImportError:
    _tqdm = None


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Directories that are always skipped when walking the file tree.
DEFAULT_SKIP_DIRS = {
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

# re.* functions whose first string argument is treated as a regex pattern.
DEFAULT_REGEX_FUNCTIONS = {
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

# Matches an unescaped backslash that is NOT followed by a valid escape char.
INVALID_BACKSLASH_PATTERN = re.compile(r'(?<!\\)\\(?![\\\'"abfnrtvNuUx0-7\n])')

# Matches re.<func>("...") calls via regex (used by the extract subcommand).
REGEX_CALL_PATTERN = re.compile(
    r"re\.(?:compile|search|match|findall|fullmatch|finditer)\s*"
    r'\(\s*([rR]?["\'])(.*?)(?<!\\)\1',
    re.DOTALL,
)

# Matches a full Python string literal including prefix and quotes.
STRING_LITERAL_PATTERN = re.compile(
    r"^([rubfRUBF]*)(\"\"\"|\'\'\'|\"|\')(.*)(\2)$",
    re.DOTALL,
)

# Token types that should be ignored when scanning for string literals.
IGNORED_TOKEN_TYPES = {
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
# Helper utilities
# ---------------------------------------------------------------------------


def relative_path_for_display(path: pathlib.Path) -> pathlib.Path:
    """
    Return *path* relative to the current working directory when possible.

    Falls back to the absolute path when the file lives on a different
    drive (Windows) or cannot be made relative for any other reason.
    """
    try:
        return pathlib.Path(os.path.relpath(path, pathlib.Path.cwd()))
    except ValueError:
        return path


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
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceReplacement:
    """A single source-code replacement."""

    start: tuple[int, int]
    end: tuple[int, int]
    original: str
    modified: str


@dataclass
class FileResult:
    """Generic per-file result container."""

    path: pathlib.Path
    status: str = "unchanged"
    message: str = ""
    has_issues: bool = False
    fixed: bool = False
    messages: list[str] = field(default_factory=list)
    changes: int = 0
    diff: str = ""


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def find_python_files(
    paths: Iterable[str | os.PathLike],
    *,
    follow_symlinks: bool = False,
    skip_dirs: set[str] | None = None,
    exclude_self: bool = True,
) -> list[pathlib.Path]:
    """
    Return a sorted list of Python files under *paths*.

    If *paths* is empty, the current directory is used.
    """
    if not paths:
        paths = [pathlib.Path.cwd()]

    skip_dirs = skip_dirs if skip_dirs is not None else DEFAULT_SKIP_DIRS
    this_file = pathlib.Path(__file__).resolve() if exclude_self else None
    collected: set[pathlib.Path] = set()

    for raw_path in paths:
        root = pathlib.Path(raw_path).resolve()
        if not root.exists():
            continue

        if root.is_file():
            if root.suffix == ".py" and (this_file is None or root != this_file):
                collected.add(root)
            continue

        if not root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            current_dir = pathlib.Path(dirpath)

            dirnames[:] = [
                d
                for d in dirnames
                if d not in skip_dirs
                and (follow_symlinks or not (current_dir / d).is_symlink())
            ]

            for filename in filenames:
                if not filename.endswith(".py"):
                    continue

                candidate = current_dir / filename
                if not follow_symlinks and candidate.is_symlink():
                    continue
                if this_file is not None and candidate.resolve() == this_file:
                    continue

                collected.add(candidate.resolve())

    return sorted(collected)


# ---------------------------------------------------------------------------
# String literal helpers
# ---------------------------------------------------------------------------


def parse_string_literal(literal: str) -> tuple[str, str, str] | None:
    """
    Parse a Python string literal into ``(prefix, quote, body)``.

    Returns ``None`` if *literal* is not recognised.
    """
    match = STRING_LITERAL_PATTERN.match(literal)
    if not match:
        return None
    prefix, quote, body = match.group(1), match.group(2), match.group(3)
    return prefix, quote, body


def ensure_raw_prefix(prefix: str) -> str:
    """
    Add an ``r`` prefix to a string prefix if not already present.

    ``u`` is dropped because ``ur`` is invalid in Python 3.
    """
    if "r" in prefix.lower():
        return prefix
    without_u = "".join(ch for ch in prefix if ch.lower() != "u")
    return "r" + without_u


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
        new_prefix = ensure_raw_prefix(prefix)
        return f"{new_prefix}{quote}{body}{quote}"

    if mode == "unescape-double-backslashes":
        unescaped = body.replace("\\\\", "\\")
        new_prefix = ensure_raw_prefix(prefix)
        return f"{new_prefix}{quote}{unescaped}{quote}"

    return literal


def literal_has_invalid_escape(literal: str) -> bool:
    """
    Return True if compiling ``x=literal`` emits an invalid-escape warning.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(f"x={literal}", "<string>", "exec")
        except SyntaxError:
            return False

        for warning in caught:
            if issubclass(
                warning.category, SyntaxWarning
            ) and "invalid escape sequence" in str(warning.message):
                return True
    return False


# ---------------------------------------------------------------------------
# Source rewriting
# ---------------------------------------------------------------------------


def apply_replacements(source: str, replacements: list[SourceReplacement]) -> str:
    """
    Apply *modifications* to *source*.

    Modifications are applied from the end of the file backwards so that
    earlier offsets remain valid.
    """
    ordered = list(replacements)
    if not ordered:
        return source

    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def line_col_to_offset(position: tuple[int, int]) -> int:
        line_no, col = position
        return offsets[line_no - 1] + col

    result = source
    for replacement in sorted(
        ordered,
        key=lambda r: (r.start[0], r.start[1]),
        reverse=True,
    ):
        start_offset = line_col_to_offset(replacement.start)
        end_offset = line_col_to_offset(replacement.end)
        result = result[:start_offset] + replacement.modified + result[end_offset:]
    return result


# ---------------------------------------------------------------------------
# Compile-time validation
# ---------------------------------------------------------------------------


def compile_and_collect_issues(
    data: str | bytes,
    filename: str,
) -> tuple[bool, list[str]]:
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
                messages.append(f"Line {exc.lineno}:SyntaxError:{exc.msg}")

        for warning in caught:
            if issubclass(
                warning.category, SyntaxWarning
            ) and "invalid escape sequence" in str(warning.message):
                has_issues = True
                line = getattr(warning, "lineno", "Unknown")
                messages.append(f"Line {line}:SyntaxWarning:{warning.message}")

    return has_issues, messages


# ---------------------------------------------------------------------------
# Strategy 1: add r-prefix via tokenize
# ---------------------------------------------------------------------------


def add_raw_prefix_to_file(path: pathlib.Path) -> bool:
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

    replacements: list[SourceReplacement] = []
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        if not literal_has_invalid_escape(token.string):
            continue

        converted = convert_string_literal(token.string, "add-r")
        if converted != token.string:
            replacements.append(
                SourceReplacement(
                    start=token.start,
                    end=token.end,
                    original=token.string,
                    modified=converted,
                )
            )

    if not replacements:
        return False

    new_source = apply_replacements(source, replacements)

    try:
        ast.parse(new_source)
    except SyntaxError:
        return False

    path.write_text(new_source, encoding=encoding)
    return True


# ---------------------------------------------------------------------------
# Strategy 2: double-escape invalid backslashes globally
# ---------------------------------------------------------------------------


def double_escape_backslashes(
    path: pathlib.Path,
    *,
    apply_fix: bool,
) -> tuple[int, bool]:
    """
    Count invalid backslashes in *path* and optionally double-escape them.

    Returns ``(count, fixed)``.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return 0, False

    matches = list(INVALID_BACKSLASH_PATTERN.finditer(source))
    count = len(matches)

    if count == 0 or not apply_fix:
        return count, False

    fixed_source = INVALID_BACKSLASH_PATTERN.sub("\\\\\\\\", source)

    try:
        path.write_text(fixed_source, encoding="utf-8")
    except Exception:
        return count, False

    return count, True


# ---------------------------------------------------------------------------
# Per-file processing for the "escapes" subcommand
# ---------------------------------------------------------------------------


def process_file_for_escapes(
    path: pathlib.Path,
    *,
    apply_fix: bool,
    strategy: str,
) -> FileResult:
    """Process one file for invalid string escape sequences."""
    result = FileResult(path=relative_path_for_display(path))

    try:
        data = path.read_bytes()
    except Exception as exc:
        result.messages.append(f"Could not read file:{exc}")
        return result

    has_issues, messages = compile_and_collect_issues(data, str(path))
    result.has_issues = has_issues
    result.messages = messages

    if not has_issues or not apply_fix:
        return result

    if strategy == "r-prefix":
        result.fixed = add_raw_prefix_to_file(path)
    elif strategy == "double-backslash":
        count, fixed = double_escape_backslashes(path, apply_fix=True)
        result.fixed = fixed
        if fixed:
            result.messages.append(f"Double-escaped {count} invalid backslash(es)")
    else:
        result.messages.append(f"Unknown strategy:{strategy}")

    return result


# ---------------------------------------------------------------------------
# Per-file processing for the "backslashes" subcommand
# ---------------------------------------------------------------------------


def process_file_for_backslashes(
    path: pathlib.Path,
    *,
    apply_fix: bool,
) -> FileResult:
    """Process one file using the global invalid-backslash regex."""
    result = FileResult(path=relative_path_for_display(path))

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        result.messages.append(f"Error reading file:{exc}")
        return result

    matches = list(INVALID_BACKSLASH_PATTERN.finditer(source))
    result.changes = len(matches)

    if result.changes == 0:
        return result

    result.has_issues = True
    result.messages.append(f"{result.changes} invalid escape sequence(s)")

    if apply_fix:
        fixed_source = INVALID_BACKSLASH_PATTERN.sub("\\\\\\\\", source)
        try:
            path.write_text(fixed_source, encoding="utf-8")
            result.fixed = True
            result.status = "fixed"
        except Exception as exc:
            result.messages.append(f"Failed to write:{exc}")

    return result


# ---------------------------------------------------------------------------
# re.* string literal detection
# ---------------------------------------------------------------------------


def find_regex_calls_tokenize(
    source: str,
    *,
    mode: str,
    regex_functions: set[str],
) -> list[SourceReplacement]:
    """
    Find ``re.func("...")`` calls via tokenize and return replacements.
    """
    replacements: list[SourceReplacement] = []

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return replacements

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "re":
            continue
        if index + 4 >= len(tokens):
            continue

        dot_token = tokens[index + 1]
        func_token = tokens[index + 2]
        open_paren = tokens[index + 3]
        arg_token = tokens[index + 4]

        if (
            dot_token.type == tokenize.OP
            and dot_token.string == "."
            and func_token.type == tokenize.NAME
            and func_token.string in regex_functions
            and open_paren.type == tokenize.OP
            and open_paren.string == "("
            and arg_token.type == tokenize.STRING
        ):
            converted = convert_string_literal(arg_token.string, mode)
            if converted != arg_token.string:
                replacements.append(
                    SourceReplacement(
                        start=arg_token.start,
                        end=arg_token.end,
                        original=arg_token.string,
                        modified=converted,
                    )
                )

    return replacements


def find_regex_calls_ast(
    source: str,
    *,
    regex_functions: set[str],
) -> list[SourceReplacement]:
    """
    Find ``re.func("...")`` calls via AST and return line-preserving replacements.
    """
    replacements: list[SourceReplacement] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return replacements

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
            and func.attr in regex_functions
            and node.args
        ):
            continue

        first_arg = node.args[0]
        if not (
            isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)
        ):
            continue

        literal = ast.get_source_segment(source, first_arg)
        if literal is None:
            continue

        converted = convert_string_literal(literal, "add-r")
        if converted == literal:
            continue

        replacements.append(
            SourceReplacement(
                start=(first_arg.lineno, first_arg.col_offset),
                end=(first_arg.end_lineno, first_arg.end_col_offset),
                original=literal,
                modified=converted,
            )
        )

    return replacements


def convert_unicode_escapes_ast(
    source: str,
    *,
    regex_functions: set[str],
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

    class RegexUnicodeEscapeTransformer(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.Call:
            nonlocal changes
            self.generic_visit(node)

            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "re"
                and func.attr in regex_functions
                and node.args
            ):
                return node

            first_arg = node.args[0]
            if not (
                isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)
            ):
                return node

            original = first_arg.value
            escaped = original.encode("unicode_escape").decode("ascii")
            escaped = escaped.replace("\\n", "\n")
            escaped = escaped.replace("\\t", "\t")
            escaped = escaped.replace("\\r", "\r")

            if escaped != original:
                first_arg.value = escaped
                changes += 1

            return node

    transformer = RegexUnicodeEscapeTransformer()
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree), changes


# ---------------------------------------------------------------------------
# Per-file processing for the "regex" subcommand
# ---------------------------------------------------------------------------


def process_file_for_regex(
    path: pathlib.Path,
    *,
    method: str,
    conversion: str,
    dry_run: bool,
    create_backup: bool,
    backup_suffix: str,
    regex_functions: set[str],
) -> FileResult:
    """Process one file for ``re.*`` string-literal conversion."""
    result = FileResult(path=relative_path_for_display(path))

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        result.status = "error"
        result.message = f"Failed to read:{exc}"
        return result

    if "re." not in source:
        result.message = "No re calls found"
        return result

    if method == "tokenize":
        replacements = find_regex_calls_tokenize(
            source,
            mode=conversion,
            regex_functions=regex_functions,
        )
        if not replacements:
            result.message = "No changes needed"
            return result
        new_source = apply_replacements(source, replacements)
        change_count = len(replacements)

    elif method == "ast":
        if conversion == "unicode-escape":
            new_source, change_count = convert_unicode_escapes_ast(
                source,
                regex_functions=regex_functions,
            )
        else:
            replacements = find_regex_calls_ast(
                source,
                regex_functions=regex_functions,
            )
            if not replacements:
                result.message = "No changes needed"
                return result
            new_source = apply_replacements(source, replacements)
            change_count = len(replacements)

    else:
        result.status = "error"
        result.message = f"Unknown method:{method}"
        return result

    if change_count == 0:
        result.message = "No changes needed"
        return result

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        result.status = "error"
        result.message = f"Validation failed-syntax error after conversion:{exc}"
        return result

    result.changes = change_count

    if dry_run:
        diff = difflib.unified_diff(
            source.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile=str(relative_path_for_display(path)),
            tofile=str(relative_path_for_display(path)),
        )
        result.status = "would_modify"
        result.message = f"Would modify {change_count} string(s)"
        result.diff = "".join(diff)
        return result

    if create_backup:
        backup_path = path.with_suffix(path.suffix + backup_suffix)
        try:
            shutil.copy2(path, backup_path)
        except Exception as exc:
            result.status = "error"
            result.message = f"Failed to create backup:{exc}"
            return result

    try:
        path.write_text(new_source, encoding="utf-8")
    except Exception as exc:
        result.status = "error"
        result.message = f"Failed to write:{exc}"
        return result

    result.status = "modified"
    result.message = f"Modified {change_count} string(s)"
    return result


# ---------------------------------------------------------------------------
# Per-file processing for the "extract" subcommand
# ---------------------------------------------------------------------------


def extract_patterns_from_file(
    path: pathlib.Path,
    output_dir: pathlib.Path,
) -> tuple[pathlib.Path, int]:
    """Extract regex patterns from one file and write them to *output_dir*."""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return relative_path_for_display(path), 0

    matches = REGEX_CALL_PATTERN.findall(source)
    if not matches:
        return relative_path_for_display(path), 0

    try:
        relative = path.relative_to(pathlib.Path.cwd())
    except ValueError:
        relative = path

    output_name = str(relative).replace(os.sep, "_") + ".txt"
    output_path = output_dir / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(matches), encoding="utf-8")

    return relative_path_for_display(path), len(matches)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def parse_skip_dirs(raw: str) -> set[str]:
    """Parse a comma-separated skip-dir list."""
    if not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def parse_regex_functions(raw: str) -> set[str]:
    """Parse a comma-separated ``re`` function list."""
    return {item.strip() for item in raw.split(",") if item.strip()}


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def run_escapes(args: argparse.Namespace) -> int:
    """Implement the ``escapes`` subcommand."""
    skip_dirs = parse_skip_dirs(args.skip_dirs)
    files = find_python_files(
        args.paths,
        follow_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Scanning {len(files)} Python files...")
        if args.auto_fix:
            print(f"Auto-fix enabled (strategy:{args.strategy})")

    results: list[FileResult] = []
    with futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_path = {
            executor.submit(
                process_file_for_escapes,
                path,
                apply_fix=args.auto_fix,
                strategy=args.strategy,
            ): path
            for path in files
        }
        for future in futures.as_completed(future_to_path):
            results.append(future.result())

    files_with_issues = 0
    files_fixed = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if not result.has_issues:
            continue
        files_with_issues += 1
        tag = "FIXED" if result.fixed else "WARNING"
        if not args.quiet:
            print(f"[{tag}] {result.path}")
            for message in result.messages:
                print(f"->{message}")
            print()
        if result.fixed:
            files_fixed += 1

    if not args.quiet:
        print("-" * 40)
        print("Scan Complete.")
        print(f"Files with issues:{files_with_issues}")
        if args.auto_fix:
            print(f"Files successfully fixed:{files_fixed}")

    return 0


def run_backslashes(args: argparse.Namespace) -> int:
    """Implement the ``backslashes`` subcommand."""
    skip_dirs = parse_skip_dirs(args.skip_dirs)
    files = find_python_files(
        args.paths,
        follow_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Scanning {len(files)} Python files...")

    results: list[FileResult] = []
    with futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_path = {
            executor.submit(
                process_file_for_backslashes,
                path,
                apply_fix=args.auto_fix,
            ): path
            for path in files
        }
        for future in futures.as_completed(future_to_path):
            results.append(future.result())

    files_with_issues = 0
    total_issues = 0
    files_fixed = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if result.changes == 0:
            continue
        files_with_issues += 1
        total_issues += result.changes
        tag = "FIXED" if result.fixed else "FOUND"
        if not args.quiet:
            print(f"[{tag}] {result.path}:{result.changes} invalid escape sequence(s)")
        if result.fixed:
            files_fixed += 1

    if not args.quiet:
        print("\n---Summary---")
        print(f"Files scanned:{len(files)}")
        print(f"Files with issues:{files_with_issues}")
        print(f"Total issues:{total_issues}")
        if args.auto_fix:
            print(f"Files fixed:{files_fixed}")

    return 1 if files_with_issues and not args.auto_fix else 0


def run_regex(args: argparse.Namespace) -> int:
    """Implement the ``regex`` subcommand."""
    if args.method == "tokenize" and args.convert == "unicode-escape":
        print(
            "Error:--convert unicode-escape requires--method ast.",
            file=sys.stderr,
        )
        return 2

    skip_dirs = parse_skip_dirs(args.skip_dirs)
    regex_functions = parse_regex_functions(args.functions)
    files = find_python_files(
        args.paths,
        follow_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    if not args.quiet:
        print(f"Found {len(files)} Python files")
        print(f"Method:{args.method},convert:{args.convert}")
        print(f"Workers:{args.workers}")
        if args.dry_run:
            print("DRY RUN-no files will be modified")
        if args.backup:
            print(f"Backup suffix:{args.backup_suffix}")

    results: list[FileResult] = []
    with futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_path = {
            executor.submit(
                process_file_for_regex,
                path,
                method=args.method,
                conversion=args.convert,
                dry_run=args.dry_run,
                create_backup=args.backup,
                backup_suffix=args.backup_suffix,
                regex_functions=regex_functions,
            ): path
            for path in files
        }
        for future in futures.as_completed(future_to_path):
            results.append(future.result())

    modified_count = 0
    error_count = 0

    for result in sorted(results, key=lambda r: str(r.path)):
        if result.status == "error":
            error_count += 1
            log_error(f"ERROR {result.path}:{result.message}")
        elif result.status == "modified":
            modified_count += 1
            if not args.quiet:
                print(f"FIXED {result.path}:{result.message}")
        elif result.status == "would_modify":
            modified_count += 1
            if not args.quiet:
                print(f"WOULD MODIFY {result.path}:{result.message}")
                if args.verbose and result.diff:
                    print(result.diff)
        elif args.verbose and result.status == "unchanged":
            print(f"UNCHANGED {result.path}:{result.message}")

    if not args.quiet:
        print("-" * 40)
        print("Summary:")
        print(f"  Total files:{len(files)}")
        print(f"  Modified/would modify:{modified_count}")
        print(f"  Errors:{error_count}")

    return 1 if error_count else 0


def run_extract(args: argparse.Namespace) -> int:
    """Implement the ``extract`` subcommand."""
    skip_dirs = parse_skip_dirs(args.skip_dirs)
    files = find_python_files(
        args.paths,
        follow_symlinks=args.include_symlinks,
        skip_dirs=skip_dirs,
    )

    if not files:
        print("No Python files found.")
        return 0

    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print(f"Extracting regex patterns from {len(files)} files into {output_dir}")

    progress = None
    if _tqdm is not None and not args.quiet:
        progress = _tqdm(total=len(files), desc="Progress", unit="file")

    processed = 0
    total_patterns = 0

    with futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_path = {
            executor.submit(extract_patterns_from_file, path, output_dir): path
            for path in files
        }
        for future in futures.as_completed(future_to_path):
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
        print(f"Total regex patterns extracted:{total_patterns}")

    return 0


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the full CLI parser."""
    parser = argparse.ArgumentParser(
        prog="pyescape_tool.py",
        description="Find/fix invalid Python escape sequences and regex literals.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared parent parser for common arguments.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default:current directory).",
    )
    common.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="Number of worker processes/threads (default:min(8,CPU count)).",
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
    escapes_parser = subparsers.add_parser(
        "escapes",
        parents=[common],
        help="Find/fix invalid string escape sequences.",
    )
    escapes_parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Apply fixes automatically.",
    )
    escapes_parser.add_argument(
        "--strategy",
        choices=["r-prefix", "double-backslash"],
        default="r-prefix",
        help="Fix strategy (default:r-prefix).",
    )
    escapes_parser.set_defaults(func=run_escapes)

    # backslashes
    backslashes_parser = subparsers.add_parser(
        "backslashes",
        parents=[common],
        help="Double-escape invalid backslashes globally.",
    )
    backslashes_parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Apply fixes automatically.",
    )
    backslashes_parser.set_defaults(func=run_backslashes)

    # regex
    regex_parser = subparsers.add_parser(
        "regex",
        parents=[common],
        help="Convert string literals passed to re.*functions.",
    )
    regex_parser.add_argument(
        "--method",
        choices=["tokenize", "ast"],
        default="ast",
        help="Detection method (default:tokenize).",
    )
    regex_parser.add_argument(
        "--convert",
        choices=["add-r", "unescape-double-backslashes", "unicode-escape"],
        default="add-r",
        help="Conversion mode (default:add-r).",
    )
    regex_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without writing files.",
    )
    regex_parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a backup before writing.",
    )
    regex_parser.add_argument(
        "--backup-suffix",
        default=".bak",
        help="Backup suffix (default:.bak).",
    )
    regex_parser.add_argument(
        "--functions",
        default=",".join(sorted(DEFAULT_REGEX_FUNCTIONS)),
        help="Comma-separated re.*function names to process.",
    )
    regex_parser.set_defaults(func=run_regex)

    # extract
    extract_parser = subparsers.add_parser(
        "extract",
        parents=[common],
        help="Extract regex patterns from re.*calls.",
    )
    extract_parser.add_argument(
        "--output-dir",
        "-o",
        default="output",
        help="Output directory (default:output).",
    )
    extract_parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Thread workers for extraction (default:8).",
    )
    extract_parser.set_defaults(func=run_extract)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
