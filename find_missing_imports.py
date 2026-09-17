#!/data/data/com.termux/files/home/.local/bin/python
"""Generate a Python CLI tool that scans a directory tree for Python files, uses AST analysis to detect references to standard-library modules that are used but never imported or assigned, reports only the files that contain missing imports with their line numbers, optionally auto-inserts the missing import statements, and runs the scan in parallel with a fixed multiprocessing.Pool of 8 workers, using loguru for logging and pathlib for filesystem paths, while ignoring the deprecated ``imp`` module."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import multiprocessing
import sys
import textwrap
from pathlib import Path
from typing import Final

from loguru import logger

STDLIB_MODULES: set[str] = set(sys.builtin_module_names)
for module_name in list(sys.modules.keys()):
    if hasattr(importlib.util, "find_spec"):
        try:
            spec = importlib.util.find_spec(module_name)
            if spec and spec.origin and ("site-packages" not in spec.origin):
                STDLIB_MODULES.add(module_name.split(".")[0])
        except (ImportError, ModuleNotFoundError, ValueError):
            pass

COMMON_STDLIB: Final[set[str]] = {
    "abc",
    "argparse",
    "array",
    "asyncio",
    "base64",
    "bisect",
    "builtins",
    "bz2",
    "calendar",
    "cmath",
    "cmd",
    "code",
    "codecs",
    "codeop",
    "collections",
    "colorsys",
    "compileall",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "copyreg",
    "cProfile",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "doctest",
    "email",
    "encodings",
    "ensurepip",
    "enum",
    "errno",
    "faulthandler",
    "fcntl",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "grp",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "imaplib",
    "imghdr",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "lib2to3",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "mailcap",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "msilib",
    "msvcrt",
    "multiprocessing",
    "netrc",
    "nis",
    "nntplib",
    "numbers",
    "operator",
    "optparse",
    "os",
    "ossaudiodev",
    "parser",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posix",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "pwd",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "site",
    "smtpd",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "spwd",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symbol",
    "symtable",
    "sys",
    "sysconfig",
    "syslog",
    "tabnanny",
    "tarfile",
    "telnetlib",
    "tempfile",
    "termios",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "tkinter",
    "token",
    "tokenize",
    "trace",
    "traceback",
    "tracemalloc",
    "tty",
    "turtle",
    "turtledemo",
    "types",
    "typing",
    "typing_extensions",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "winsound",
    "wsgiref",
    "xdrlib",
    "xml",
    "xmlrpc",
    "zipapp",
    "zipfile",
    "zipimport",
    "zlib",
    "zoneinfo",
}

BUILTIN_NAMES: Final[set[str]] = {
    "print",
    "len",
    "range",
    "str",
    "int",
    "float",
    "list",
    "dict",
    "set",
    "tuple",
    "bool",
    "bytes",
    "bytearray",
    "object",
    "type",
    "super",
    "property",
    "classmethod",
    "staticmethod",
    "open",
    "input",
    "enumerate",
    "zip",
    "map",
    "filter",
    "sorted",
    "reversed",
    "sum",
    "min",
    "max",
    "all",
    "any",
    "abs",
    "round",
    "pow",
    "divmod",
    "hex",
    "oct",
    "bin",
    "ord",
    "chr",
    "ascii",
    "repr",
    "format",
    "hash",
    "id",
    "isinstance",
    "issubclass",
    "callable",
    "iter",
    "next",
    "compile",
    "eval",
    "exec",
    "globals",
    "locals",
    "vars",
    "dir",
    "help",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "Exception",
    "BaseException",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "NameError",
    "IOError",
    "OSError",
    "ImportError",
    "ModuleNotFoundError",
    "StopIteration",
    "GeneratorExit",
    "KeyboardInterrupt",
    "SystemExit",
    "NotImplemented",
    "Ellipsis",
    "None",
    "True",
    "False",
    "__name__",
    "__doc__",
    "__package__",
    "__file__",
    "__cached__",
    "__loader__",
    "__spec__",
}

IGNORED_MODULES: Final[set[str]] = {"imp", "cmd", "keyword", "token"}


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor that collects imported, used, and assigned names."""

    def __init__(self) -> None:
        """Initialize empty tracking sets for imports, usages, and assignments."""
        self.imported_names: set[str] = set()
        self.used_names: set[str] = set()
        self.assigned_names: set[str] = set()
        self.import_lines: dict[str, int] = {}

    def visit_Import(self, node: ast.Import) -> None:
        """Record names introduced by ``import`` statements."""
        for alias in node.names:
            base_name = alias.name.split(".")[0]
            self.imported_names.add(base_name)
            self.import_lines[base_name] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record names introduced by ``from ... import ...`` statements."""
        if node.module:
            base_name = node.module.split(".")[0]
            self.imported_names.add(base_name)
            self.import_lines[base_name] = node.lineno
        for alias in node.names:
            if alias.name != "*":
                self.imported_names.add(alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record simple and tuple/list-unpacked assignment targets."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned_names.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in ast.walk(target):
                    if isinstance(elt, ast.Name):
                        self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Record augmented assignment targets."""
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Record annotated assignment targets."""
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """Record loop variable names."""
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in ast.walk(node.target):
                if isinstance(elt, ast.Name):
                    self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Record ``with ... as ...`` target names."""
        for item in node.items:
            if item.optional_vars:
                if isinstance(item.optional_vars, ast.Name):
                    self.assigned_names.add(item.optional_vars.id)
                elif isinstance(item.optional_vars, (ast.Tuple, ast.List)):
                    for elt in ast.walk(item.optional_vars):
                        if isinstance(elt, ast.Name):
                            self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Record ``except ... as ...`` target names."""
        if node.name:
            self.assigned_names.add(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Record function name and parameter names."""
        self.assigned_names.add(node.name)
        for arg in node.args.args:
            self.assigned_names.add(arg.arg)
        if node.args.vararg:
            self.assigned_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.assigned_names.add(node.args.kwarg.arg)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Record async function name and parameter names."""
        self.assigned_names.add(node.name)
        for arg in node.args.args:
            self.assigned_names.add(arg.arg)
        if node.args.vararg:
            self.assigned_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.assigned_names.add(node.args.kwarg.arg)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Record class names."""
        self.assigned_names.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Record names loaded in expressions."""
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Record the base name of attribute accesses such as ``os.path``."""
        if isinstance(node.value, ast.Name):
            self.used_names.add(node.value.id)
        self.generic_visit(node)


def get_stdlib_modules() -> set[str]:
    """Return the set of known standard-library module names."""
    stdlib = set(sys.builtin_module_names)
    stdlib.update(COMMON_STDLIB)
    return stdlib


def analyze_file(path: Path) -> tuple[Path, list[tuple[str, int]]]:
    """Analyze one Python file and return missing stdlib imports with line numbers."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, str(path))
        analyzer = ImportAnalyzer()
        analyzer.visit(tree)
        stdlib = get_stdlib_modules()
        missing_imports: list[tuple[str, int]] = []
        for name in analyzer.used_names:
            if (
                name not in analyzer.imported_names
                and name not in analyzer.assigned_names
                and name not in BUILTIN_NAMES
                and name in stdlib
                and name not in IGNORED_MODULES
                and not name.startswith("_")
            ):
                line_num = 0
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == name:
                        line_num = node.lineno
                        break
                missing_imports.append((name, line_num or 1))
        return (path, missing_imports)
    except (SyntaxError, UnicodeDecodeError):
        return (path, [])


def autofix_imports(path: Path, missing_imports: list[tuple[str, int]]) -> bool:
    """Insert missing ``import`` statements into a file and return whether it changed."""
    if not missing_imports:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        unique_imports = sorted({imp[0] for imp in missing_imports})
        insert_idx = 0
        in_imports = True
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("import ", "from ")):
                insert_idx = i + 1
            elif in_imports and not stripped.startswith(("import ", "from ")):
                in_imports = False
        new_imports = [f"import {imp}\n" for imp in unique_imports]
        lines[insert_idx:insert_idx] = new_imports
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


def main() -> None:
    """Parse arguments, scan for missing stdlib imports, and optionally autofix them."""
    parser = argparse.ArgumentParser(
        description="Find and fix missing stdlib imports in Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python find_missing_imports.py
              python find_missing_imports.py --autofix
        """),
    )
    parser.add_argument(
        "-a", "--autofix", action="store_true", help="Automatically add missing imports"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()

    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        logger.error(f"Error: {root_dir} is not a directory")
        sys.exit(1)

    py_files = list(root_dir.glob("**/*.py"))
    if not py_files:
        print(f"No Python files found in {root_dir}")
        sys.exit(0)

    total_missing = 0
    fixed_files = 0

    with multiprocessing.Pool(processes=8) as pool:
        results = [pool.apply_async(analyze_file, (py_file,)) for py_file in py_files]
        for result in results:
            path, missing_imports = result.get()
            if not missing_imports:
                continue
            total_missing += len(missing_imports)
            rel_path = path.relative_to(root_dir)
            logger.warning(f"{rel_path}:")
            for module, lineno in sorted(set(missing_imports)):
                logger.warning(f"  Line {lineno}: missing `import {module}`")
            if args.autofix:
                if autofix_imports(path, missing_imports):
                    logger.success("  ✓ Fixed")
                    fixed_files += 1
                else:
                    logger.error("  ✗ Failed to fix")

    print(f"{'─' * 40}")
    print(f"Total missing imports found: {total_missing}")
    if args.autofix:
        print(f"Files fixed: {fixed_files}")

    sys.exit(1 if total_missing > 0 else 0)


if __name__ == "__main__":
    raise SystemExit(main())
