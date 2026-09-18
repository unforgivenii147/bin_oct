#!/data/data/com.termux/files/home/.local/bin/python
"""Detect (and optionally remove) unused imports from Python source files.

Two detection engines are available:

* **Built-in AST analyzer** (default) — fast, in-process, no external
  dependencies.  Understands ``from __future__ import ...``,
  ``if TYPE_CHECKING:`` blocks, ``__all__ = [...]`` re-exports, and
  ``import *``.  Used for both detection and in-place autofix.
* **autoflake** (``--autoflake``) — delegates to the external
  ``autoflake`` program.  Requires ``autoflake`` on ``$PATH``
  (``pip install autoflake``).  Detection works on real files *and*
  archive members; autofix is only possible on real files.

The tool understands plain ``.py`` files, wheel archives (``.whl``), and
zstd-compressed tarballs (``.tar.zst``).  When the optional ``zstandard``
package is not installed, a plain ``tarfile`` fallback is attempted for
``.tar.zst`` inputs.

Autofix caveats
---------------
The built-in rewriter re-parses each affected line individually so that
it can strip only the unused aliases from a comma-separated import.
Lines that do not parse on their own (e.g. continuations of a multi-line
import) are skipped, which is why archive-member pseudo-paths
(``archive::member``) are never autofixed by the AST engine.
"""

from __future__ import annotations

import ast
import difflib
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path
from typing import Sequence

try:
    import zstandard as zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

#: Fixed size of the multiprocessing pool.  Kept as a module constant
#: because the CLI no longer exposes a ``--workers`` flag.
WORKERS = 8


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class UnusedImport:
    """A single import statement that has one or more unused names."""

    lineno: int
    col_offset: int
    statement: str
    unused_names: list[str] = field(default_factory=list)
    module_path: str = ""


@dataclass
class FileReport:
    """Analysis result for a single source file (real or archive member)."""

    path: str
    unused_imports: list[UnusedImport] = field(default_factory=list)
    error: str | None = None
    file_size: int = 0


@dataclass
class AutoflakeReport:
    """Result of running the external ``autoflake`` tool on one source."""

    path: str
    diff: str = ""
    fixed_source: str = ""
    error: str | None = None

    @property
    def has_unused(self) -> bool:
        """True when autoflake produced a different source."""
        return bool(self.diff)


# ---------------------------------------------------------------------------
# ANSI color helper
# ---------------------------------------------------------------------------


class Colors:
    """ANSI escape codes; call :meth:`disable` to blank them all out."""

    BOLD = "\x1b[1m"
    CYAN = "\x1b[36m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    RESET = "\x1b[0m"

    @classmethod
    def disable(cls) -> None:
        """Replace every public color attribute with an empty string."""
        for attr in dir(cls):
            if not attr.startswith("_") and attr != "disable":
                setattr(cls, attr, "")


# ---------------------------------------------------------------------------
# AST visitors (built-in engine)
# ---------------------------------------------------------------------------


class ImportVisitor(ast.NodeVisitor):
    """Collect every imported name and the contexts that protect it.

    Protected contexts suppress unused-import warnings:

    * ``future_imports``        — ``from __future__ import ...``
    * ``type_checking_imports`` — imports inside ``if TYPE_CHECKING:``
    * ``all_export``            — strings listed in ``__all__``
    * ``star_imports``          — modules referenced by ``from m import *``
    """

    def __init__(self) -> None:
        self.imports: dict[str, tuple[int, int, str]] = {}
        self.type_checking_imports: set[str] = set()
        self.future_imports: set[str] = set()
        self.all_export: set[str] = set()
        self.star_imports: set[str] = set()
        self._in_type_checking: bool = False

    # -- control-flow context ------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        """Track whether we are inside an ``if TYPE_CHECKING:`` block."""
        is_tc = (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        ) or (
            isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
        )

        if is_tc:
            previous = self._in_type_checking
            self._in_type_checking = True
            for child in node.body:
                self.visit(child)
            self._in_type_checking = previous
            # ``else`` branch is *not* under TYPE_CHECKING.
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    # -- import handling -----------------------------------------------------

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "__future__":
            for alias in node.names:
                self.future_imports.add(alias.asname or alias.name)
            self.generic_visit(node)
            return

        if node.names and node.names[0].name == "*":
            self.star_imports.add(node.module or "")
            self.generic_visit(node)
            return

        statement = self._build_import_statement(node)
        for alias in node.names:
            name = alias.asname or alias.name
            if self._in_type_checking:
                self.type_checking_imports.add(name)
            else:
                self.imports[name] = (node.lineno, node.col_offset, statement)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        statement = self._build_import_statement(node)
        for alias in node.names:
            # ``import a.b.c`` binds the top-level name ``a``.
            name = alias.asname or alias.name.split(".")[0]
            if self._in_type_checking:
                self.type_checking_imports.add(name)
            else:
                self.imports[name] = (node.lineno, node.col_offset, statement)
        self.generic_visit(node)

    # -- ``__all__`` re-exports ---------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record string literals assigned to ``__all__``.

        Accepts list, tuple, and set literals.
        """
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "__all__"
                and isinstance(node.value, (ast.List, ast.Tuple, ast.Set))
            ):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        self.all_export.add(elt.value)
        self.generic_visit(node)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _build_import_statement(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "<import statement>"


class NameVisitor(ast.NodeVisitor):
    """Collect every identifier that appears anywhere in the module."""

    def __init__(self) -> None:
        self.used_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            self.used_names.add(node.value.id)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            identifiers = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", node.value)
            self.used_names.update(identifiers)
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Built-in analysis
# ---------------------------------------------------------------------------


def analyze_imports(
    source: str, path: str = ""
) -> tuple[list[UnusedImport], str | None]:
    """Analyse ``source`` with the built-in AST engine."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ([], f"Syntax error: {exc}")
    except Exception as exc:  # pragma: no cover — defensive
        return ([], f"Parse error: {exc}")

    import_visitor = ImportVisitor()
    import_visitor.visit(tree)

    name_visitor = NameVisitor()
    name_visitor.visit(tree)
    used_names = name_visitor.used_names

    unused: list[UnusedImport] = []
    seen_lines: set[int] = set()

    for imported_name, (
        lineno,
        col_offset,
        statement,
    ) in import_visitor.imports.items():
        if imported_name in import_visitor.future_imports:
            continue
        if imported_name in import_visitor.type_checking_imports:
            continue
        if imported_name in import_visitor.all_export:
            continue
        if imported_name in import_visitor.star_imports:
            continue
        if imported_name in used_names:
            continue

        if lineno not in seen_lines:
            unused.append(
                UnusedImport(
                    lineno=lineno,
                    col_offset=col_offset,
                    statement=statement,
                    unused_names=[imported_name],
                    module_path=path,
                )
            )
            seen_lines.add(lineno)
        else:
            for entry in unused:
                if entry.lineno == lineno:
                    entry.unused_names.append(imported_name)
                    break

    return (unused, None)


# ---------------------------------------------------------------------------
# File / archive readers
# ---------------------------------------------------------------------------


def process_py_file(path: str) -> FileReport:
    """Read and analyse a plain ``.py`` file with the AST engine."""
    path_obj = Path(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        file_size = len(source.encode("utf-8"))
    except PermissionError:
        return FileReport(str(path_obj), error="Permission denied")
    except Exception as exc:
        return FileReport(str(path_obj), error=f"Read error: {exc}")

    unused, error = analyze_imports(source, str(path_obj))
    return FileReport(
        path=str(path_obj),
        unused_imports=unused,
        error=error,
        file_size=file_size,
    )


def extract_py_files_from_wheel(wheel_path: str) -> dict[str, str]:
    """Return ``{virtual_path: source}`` for every ``.py`` inside a wheel."""
    result: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel_path, "r") as whl:
            for member in whl.namelist():
                if not member.endswith(".py"):
                    continue
                try:
                    content = whl.read(member).decode("utf-8", errors="replace")
                    result[f"{Path(wheel_path).name}::{member}"] = content
                except Exception:
                    pass
    except Exception:
        pass
    return result


def extract_py_files_from_tar_zst(archive_path: str) -> dict[str, str]:
    """Return ``{virtual_path: source}`` for every ``.py`` in a ``.tar.zst``."""
    result: dict[str, str] = {}
    prefix = Path(archive_path).name

    try:
        if HAS_ZSTD:
            with open(archive_path, "rb") as fh:
                dctx = zstd.ZstdDecompressor()
                with (
                    dctx.stream_reader(fh) as reader,
                    tarfile.open(fileobj=reader, mode="r|") as tar,
                ):
                    _collect_tar_members(tar, prefix, result)
        else:
            with tarfile.open(archive_path, "r:*") as tar:
                _collect_tar_members(tar, prefix, result)
    except Exception:
        pass
    return result


def _collect_tar_members(
    tar: tarfile.TarFile, prefix: str, result: dict[str, str]
) -> None:
    """Populate ``result`` with every ``.py`` regular file in ``tar``."""
    for member in tar:
        if not (member.isfile() and member.name.endswith(".py")):
            continue
        try:
            file_obj = tar.extractfile(member)
            if file_obj is None:
                continue
            content = file_obj.read().decode("utf-8", errors="replace")
            result[f"{prefix}::{member.name}"] = content
        except Exception:
            pass


def process_archive_member(virtual_path: str, source: str) -> FileReport:
    """Analyse a single in-memory archive member with the AST engine."""
    unused, error = analyze_imports(source, virtual_path)
    return FileReport(
        path=virtual_path,
        unused_imports=unused,
        error=error,
        file_size=len(source.encode("utf-8")),
    )


# ---------------------------------------------------------------------------
# autoflake engine
# ---------------------------------------------------------------------------

_AUTOFLACE_BASE = [
    "autoflake",
    "--remove-all-unused-imports",
    "--ignore-init-module-imports",
]


def _autoflake_build_diff(original: str, fixed: str, label: str) -> str:
    """Return a unified diff between two source strings."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def autoflake_process_path(path: str) -> AutoflakeReport:
    """Run autoflake against a real file path.

    Passing the path (rather than stdin) lets autoflake honour
    ``--ignore-init-module-imports`` for ``__init__.py`` files.
    """
    try:
        original = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return AutoflakeReport(path=path, error=f"Read error: {exc}")

    try:
        result = subprocess.run(
            [*_AUTOFLACE_BASE, path],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return AutoflakeReport(path=path, error="autoflake not installed")

    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        return AutoflakeReport(
            path=path, error=msg or f"autoflake exited {result.returncode}"
        )

    fixed = result.stdout
    if fixed == original:
        return AutoflakeReport(path=path)

    return AutoflakeReport(
        path=path,
        diff=_autoflake_build_diff(original, fixed, path),
        fixed_source=fixed,
    )


def autoflake_process_source(virtual_path: str, source: str) -> AutoflakeReport:
    """Run autoflake against an in-memory source (used for archive members).

    Note: because we go through stdin, autoflake cannot detect that the
    source corresponds to an ``__init__.py`` file.
    """
    try:
        result = subprocess.run(
            [*_AUTOFLACE_BASE, "-"],
            input=source,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return AutoflakeReport(path=virtual_path, error="autoflake not installed")

    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        return AutoflakeReport(
            path=virtual_path, error=msg or f"autoflake exited {result.returncode}"
        )

    fixed = result.stdout
    if fixed == source:
        return AutoflakeReport(path=virtual_path)

    return AutoflakeReport(
        path=virtual_path,
        diff=_autoflake_build_diff(source, fixed, virtual_path),
        fixed_source=fixed,
    )


# -- multiprocessing workers ------------------------------------------------


def _process_py_file_worker(path: str) -> FileReport:
    return process_py_file(path)


def _process_archive_worker(args: tuple[str, str]) -> FileReport:
    virtual_path, source = args
    return process_archive_member(virtual_path, source)


def _process_py_file_autoflake_worker(path: str) -> AutoflakeReport:
    return autoflake_process_path(path)


def _process_archive_autoflake_worker(args: tuple[str, str]) -> AutoflakeReport:
    virtual_path, source = args
    return autoflake_process_source(virtual_path, source)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_files(
    paths: list[str], exclude_patterns: list[str]
) -> tuple[list[str], list[tuple[str, str]]]:
    """Expand ``paths`` into ``(py_files, archive_members)``."""
    py_files: list[str] = []
    archive_members: list[tuple[str, str]] = []
    exclude_regexes = [re.compile(p) for p in exclude_patterns]

    def should_exclude(path: str) -> bool:
        return any(rx.search(path) for rx in exclude_regexes)

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print(f"⚠ Path not found: {path_str}", file=sys.stderr)
            continue

        if path.is_file():
            _collect_from_file(path, should_exclude, py_files, archive_members)
        elif path.is_dir():
            for py_file in path.rglob("*.py"):
                if not should_exclude(str(py_file)):
                    py_files.append(str(py_file))
            for whl_file in path.rglob("*.whl"):
                for vpath, source in extract_py_files_from_wheel(str(whl_file)).items():
                    if not should_exclude(vpath):
                        archive_members.append((vpath, source))
            for tar_file in path.rglob("*.tar.zst"):
                for vpath, source in extract_py_files_from_tar_zst(
                    str(tar_file)
                ).items():
                    if not should_exclude(vpath):
                        archive_members.append((vpath, source))

    return (py_files, archive_members)


def _collect_from_file(
    path: Path,
    should_exclude,
    py_files: list[str],
    archive_members: list[tuple[str, str]],
) -> None:
    """Dispatch a single file path onto the appropriate collector."""
    if path.suffix == ".py":
        if not should_exclude(str(path)):
            py_files.append(str(path))
    elif path.suffix == ".whl":
        for vpath, source in extract_py_files_from_wheel(str(path)).items():
            if not should_exclude(vpath):
                archive_members.append((vpath, source))
    elif path.suffix == ".zst" or path.name.endswith(".tar.zst"):
        for vpath, source in extract_py_files_from_tar_zst(str(path)).items():
            if not should_exclude(vpath):
                archive_members.append((vpath, source))


# ---------------------------------------------------------------------------
# AST-engine autofix — line-based rewriting
# ---------------------------------------------------------------------------


def remove_unused_imports(source: str, unused: list[UnusedImport]) -> tuple[str, bool]:
    """Return ``(new_source, ok)`` with unused aliases stripped."""
    lines = source.split("\n")
    unused_by_line: dict[int, set[str]] = {}

    for entry in unused:
        unused_by_line.setdefault(entry.lineno, set()).update(entry.unused_names)

    for lineno in sorted(unused_by_line.keys(), reverse=True):
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            continue

        line = lines[idx]
        unused_names = unused_by_line[lineno]

        try:
            tree = ast.parse(line)
            node = tree.body[0] if tree.body else None
        except Exception:
            continue

        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        new_line = _reconstruct_import_line(node, unused_names, line)
        if new_line is None:
            del lines[idx]
        else:
            lines[idx] = new_line

    result = "\n".join(lines)
    try:
        ast.parse(result)
    except SyntaxError:
        return (source, False)
    return (result, True)


def _reconstruct_import_line(
    node: ast.Import | ast.ImportFrom,
    unused_names: set[str],
    original_line: str,
) -> str | None:
    """Rebuild an import line keeping only used aliases."""
    indent = original_line[: len(original_line) - len(original_line.lstrip())]

    if isinstance(node, ast.Import):
        kept = [
            alias
            for alias in node.names
            if (alias.asname or alias.name.split(".")[0]) not in unused_names
        ]
        if not kept:
            return None
        parts = [
            f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            for alias in kept
        ]
        return f"{indent}import {', '.join(parts)}"

    if isinstance(node, ast.ImportFrom):
        kept = [
            alias
            for alias in node.names
            if (alias.asname or alias.name) not in unused_names
        ]
        if not kept:
            return None
        module = node.module or ""
        level = "." * node.level if node.level else ""
        parts = [
            f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            for alias in kept
        ]
        return f"{indent}from {level}{module} import {', '.join(parts)}"

    return original_line


def autofix_file(
    path: str, unused: list[UnusedImport], dry_run: bool = False
) -> tuple[bool, str | None]:
    """Apply :func:`remove_unused_imports` to a real file on disk."""
    if "::" in path:
        return (False, "Cannot autofix inside packed archives")

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except Exception as exc:
        return (False, f"Read error: {exc}")

    modified, success = remove_unused_imports(source, unused)
    if not success:
        return (False, "Result failed to parse")

    if dry_run:
        return (True, None)

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(modified)
    except Exception as exc:
        return (False, f"Write error: {exc}")

    return (True, None)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(
    reports: Sequence[FileReport],
    use_color: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    autofix: bool = False,
) -> None:
    """Print the AST-engine report."""
    if not use_color:
        Colors.disable()

    total_unused = 0
    files_with_issues = 0
    fixed_count = 0
    skipped_count = 0

    for report in reports:
        if report.error:
            print(f"{Colors.RED}✗ {report.path} — {report.error}{Colors.RESET}")
            continue

        if not report.unused_imports:
            if verbose:
                print(f"{Colors.GREEN}✓{Colors.RESET} {report.path}")
            continue

        files_with_issues += 1
        print(f"\n{Colors.BOLD}{report.path}{Colors.RESET}")

        for unused in report.unused_imports:
            total_unused += 1
            print(
                f"  line {Colors.CYAN}{unused.lineno:>5}{Colors.RESET}  "
                f"{Colors.YELLOW}{unused.statement}{Colors.RESET}"
            )
            names_str = ", ".join(unused.unused_names)
            print(f"{'':20}[unused: {names_str}]")

        if autofix:
            if dry_run:
                print(f"  [dry-run] would fix {report.path}")
            else:
                success, error = autofix_file(report.path, report.unused_imports)
                if success:
                    print(f"  {Colors.GREEN}fixed{Colors.RESET} {report.path}")
                    fixed_count += 1
                else:
                    print(
                        f"  {Colors.RED}SKIP{Colors.RESET} autofix on "
                        f"{report.path} — {error}"
                    )
                    skipped_count += 1

    print()
    print(f"Found {total_unused} unused import(s) across {files_with_issues} file(s).")
    if autofix:
        print(f"Fixed {fixed_count} file(s).")
        if skipped_count:
            print(f"Skipped {skipped_count} file(s).")


def print_autoflake_report(
    reports: Sequence[AutoflakeReport],
    use_color: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
    autofix: bool = False,
    show_diff: bool = False,
) -> None:
    """Print the autoflake-engine report."""
    if not use_color:
        Colors.disable()

    total_changed = 0
    fixed_count = 0
    skipped_count = 0

    for report in reports:
        if report.error:
            print(f"{Colors.RED}✗ {report.path} — {report.error}{Colors.RESET}")
            continue

        if not report.has_unused:
            if verbose:
                print(f"{Colors.GREEN}✓{Colors.RESET} {report.path}")
            continue

        total_changed += 1
        print(f"\n{Colors.BOLD}{report.path}{Colors.RESET}")

        if show_diff:
            print(report.diff, end="" if report.diff.endswith("\n") else "\n")
        else:
            print(f"  {Colors.YELLOW}unused import(s) detected{Colors.RESET}")

        if autofix:
            if "::" in report.path:
                print(f"  {Colors.RED}SKIP{Colors.RESET} cannot autofix archive member")
                skipped_count += 1
                continue
            if dry_run:
                print(f"  [dry-run] would fix {report.path}")
                continue
            try:
                Path(report.path).write_text(report.fixed_source, encoding="utf-8")
                print(f"  {Colors.GREEN}fixed{Colors.RESET} {report.path}")
                fixed_count += 1
            except Exception as exc:
                print(f"  {Colors.RED}SKIP{Colors.RESET} write error: {exc}")
                skipped_count += 1

    print()
    print(f"Found {total_changed} file(s) with unused import(s).")
    if autofix:
        print(f"Fixed {fixed_count} file(s).")
        if skipped_count:
            print(f"Skipped {skipped_count} file(s).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> ArgumentParser:
    """Construct the argument parser used by :func:`main`."""
    parser = ArgumentParser(
        description=(
            "Detect and optionally remove unused imports from Python files "
            "and archives."
        ),
        formatter_class=RawDescriptionHelpFormatter,
        epilog=(
            "\nExamples:\n"
            "  python unused_imports.py\n"
            "  python unused_imports.py src/main.py\n"
            "  python unused_imports.py src/ --autofix\n"
            "  python unused_imports.py src/ --dry-run\n"
            '  python unused_imports.py src/ --exclude "test_.*"\n'
            "  python unused_imports.py src/ --autoflake --diff\n"
            "  python unused_imports.py src/ --autoflake --autofix\n"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="File or directory paths to analyze (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Remove unused imports in-place",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing (enables --autofix)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Detailed output including files with 0 issues",
    )
    parser.add_argument(
        "--autoflake",
        action="store_true",
        help=(
            "Use the external `autoflake` program instead of the built-in "
            "AST analyzer (requires `pip install autoflake`)"
        ),
    )
    parser.add_argument(
        "-d",
        "--diff",
        action="store_true",
        help="With --autoflake, show a unified diff of the changes",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Regex pattern to exclude files (repeatable)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes",
    )
    return parser


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


def _run_ast_mode(
    py_files: list[str],
    archive_members: list[tuple[str, str]],
    args,
) -> int:
    """Run the built-in AST analyzer over the discovered files."""
    reports: list[FileReport] = []
    with Pool(processes=WORKERS) as pool:
        if py_files:
            reports.extend(pool.map(_process_py_file_worker, py_files))
        if archive_members:
            reports.extend(pool.map(_process_archive_worker, archive_members))

    print_report(
        reports,
        use_color=not args.no_color,
        verbose=args.verbose,
        dry_run=args.dry_run,
        autofix=args.autofix,
    )
    return 1 if any(report.unused_imports for report in reports) else 0


def _run_autoflake_mode(
    py_files: list[str],
    archive_members: list[tuple[str, str]],
    args,
) -> int:
    """Run the external autoflake tool over the discovered files."""
    if shutil.which("autoflake") is None:
        print(
            "Error: `autoflake` is not installed. Run `pip install autoflake`.",
            file=sys.stderr,
        )
        return 1

    reports: list[AutoflakeReport] = []
    with Pool(processes=WORKERS) as pool:
        if py_files:
            reports.extend(pool.map(_process_py_file_autoflake_worker, py_files))
        if archive_members:
            reports.extend(pool.map(_process_archive_autoflake_worker, archive_members))

    print_autoflake_report(
        reports,
        use_color=not args.no_color,
        verbose=args.verbose,
        dry_run=args.dry_run,
        autofix=args.autofix,
        show_diff=args.diff,
    )
    return 1 if any(report.has_unused for report in reports) else 0


def main() -> int:
    """Entry point.  Returns the process exit status."""
    parser = build_parser()
    args = parser.parse_args()

    # ``--dry-run`` implies ``--autofix`` but suppresses writes.
    if args.dry_run:
        args.autofix = True

    py_files, archive_members = discover_files(args.paths, args.exclude)
    if not py_files and not archive_members:
        print("No Python files found to analyze.", file=sys.stderr)
        return 1

    if args.verbose:
        engine = "autoflake" if args.autoflake else "built-in AST analyzer"
        print(
            f"Scanning {len(args.paths)} path(s) with {WORKERS} worker(s) "
            f"using {engine} …\n"
        )
        print(
            f"  {len(py_files)} .py file(s), "
            f"{len(archive_members)} archive member(s) queued.\n"
        )

    if args.autoflake:
        return _run_autoflake_mode(py_files, archive_members, args)
    return _run_ast_mode(py_files, archive_members, args)


if __name__ == "__main__":
    raise SystemExit(main())
