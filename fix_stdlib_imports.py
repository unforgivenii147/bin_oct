#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import keyword
import os
import sys
from pathlib import Path

STDLIB_MODULES = {
    "abc",
    "aifc",
    "argparse",
    "array",
    "ast",
    "asynchat",
    "asyncio",
    "asyncore",
    "atexit",
    "audioop",
    "base64",
    "bdb",
    "binascii",
    "binhex",
    "bisect",
    "builtins",
    "bz2",
    "calendar",
    "cgi",
    "cgitb",
    "chunk",
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
    "contextvars",
    "copy",
    "copyreg",
    "cProfile",
    "crypt",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "distutils",
    "doctest",
    "email",
    "encodings",
    "enum",
    "errno",
    "faulthandler",
    "fcntl",
    "filecmp",
    "fileinput",
    "fnmatch",
    "formatter",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "graphlib",
    "grp",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "idlelib",
    "imaplib",
    "imghdr",
    "imp",
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
    "multiprocessing",
    "netrc",
    "nis",
    "nntplib",
    "numbers",
    "operator",
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
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
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
    "collections.abc",
    "collections.defaultdict",
    "collections.Ordereddict",
    "os.path",
    "datetime.datetime",
    "datetime.date",
    "datetime.time",
    "datetime.timedelta",
    "json.dumps",
    "json.loads",
    "sys.argv",
    "sys.path",
    "sys.stdin",
    "sys.stdout",
    "sys.stderr",
}


def get_stdlib_names() -> dict[str, set[str]]:
    stdlib_names = {
        "os": {
            "path",
            "environ",
            "getenv",
            "listdir",
            "walk",
            "remove",
            "rename",
            "mkdir",
            "makedirs",
            "chdir",
            "getcwd",
            "sep",
            "linesep",
        },
        "sys": {
            "argv",
            "path",
            "stdin",
            "stdout",
            "stderr",
            "exit",
            "version",
            "platform",
            "executable",
            "modules",
        },
        "math": {
            "sqrt",
            "ceil",
            "floor",
            "sin",
            "cos",
            "tan",
            "pi",
            "e",
            "log",
            "log10",
            "exp",
            "pow",
            "fabs",
            "factorial",
        },
        "random": {
            "random",
            "randint",
            "choice",
            "shuffle",
            "sample",
            "uniform",
            "seed",
            "randrange",
        },
        "datetime": {"datetime", "date", "time", "timedelta", "timezone"},
        "json": {"dumps", "loads", "dump", "load"},
        "collections": {"defaultdict", "Ordereddict", "Counter", "deque", "namedtuple"},
        "itertools": {
            "chain",
            "cycle",
            "repeat",
            "count",
            "islice",
            "groupby",
            "combinations",
            "permutations",
            "product",
        },
        "functools": {"reduce", "partial", "lru_cache", "wraps", "cache"},
        "pathlib": {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"},
        "re": {"match", "search", "findall", "sub", "compile", "split", "escape"},
        "argparse": {"ArgumentParser", "Namespace"},
        "logging": {
            "debug",
            "info",
            "warning",
            "error",
            "critical",
            "getLogger",
            "basicConfig",
        },
        "statistics": {"mean", "median", "mode", "stdev", "variance"},
        "typing": {
            "list",
            "dict",
            "set",
            "tuple",
            "Optional",
            "Union",
            "Any",
            "Callable",
            "Iterator",
        },
        "decimal": {"Decimal"},
        "fractions": {"Fraction"},
        "hashlib": {"md5", "sha1", "sha256", "sha512"},
        "subprocess": {"run", "Popen", "call", "check_output"},
        "shutil": {"copy", "copy2", "move", "rmtree", "make_archive"},
        "tempfile": {"NamedTemporaryFile", "TemporaryFile", "mkdtemp"},
        "glob": {"glob"},
        "time": {
            "time",
            "sleep",
            "ctime",
            "localtime",
            "gmtime",
            "strftime",
            "strptime",
        },
    }
    for module in STDLIB_MODULES:
        if "." not in module and module not in stdlib_names:
            stdlib_names[module] = set()
    return stdlib_names


class ImportChecker(ast.NodeVisitor):
    def __init__(self, stdlib_names: dict[str, set[str]]):
        self.stdlib_names = stdlib_names
        self.imports = {}
        self.used_names = set()
        self.import_nodes = []


def find_missing_imports(
    path: str, stdlib_names: dict[str, set[str]]
) -> list[tuple[str, str]]:
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        print(f"Syntax error in {path}: {e}", file=sys.stderr)
        return []
    checker = ImportChecker(stdlib_names)
    checker.visit(tree)
    missing = []
    builtin_names = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set()
    keywords = set(keyword.kwlist)
    for name in checker.used_names:
        if name in checker.imports:
            continue
        if name in builtin_names or name in keywords:
            continue
        if name.startswith("_"):
            continue
        if name in stdlib_names:
            missing.append((name, f"import {name}"))
        else:
            for module, attrs in stdlib_names.items():
                if name in attrs:
                    if module not in checker.imports:
                        missing.append((name, f"from {module} import {name}"))
                    break
    return missing


def scan_directory(
    root_dir: str, exclude_dirs: set[str] | None = None
) -> dict[str, list[tuple[str, str]]]:
    if exclude_dirs is None:
        exclude_dirs = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            ".env",
            "build",
            "dist",
            "egg-info",
            ".tox",
            ".eggs",
        }
    stdlib_names = get_stdlib_names()
    results = {}
    root_path = Path(root_dir)
    if not root_path.exists():
        print(f"Error: Directory '{root_dir}' does not exist.", file=sys.stderr)
        return results
    python_files = list(root_path.rglob("*.py"))
    python_files = [
        f for f in python_files if not any(excl in f.parts for excl in exclude_dirs)
    ]
    print(f"Scanning {len(python_files)} Python files in {root_dir}...")
    for path in python_files:
        missing = find_missing_imports(str(path), stdlib_names)
        if missing:
            results[str(path)] = missing
    return results


def print_results(results: dict[str, list[tuple[str, str]]], show_all: bool = False):
    if not results:
        print("\n✅ No missing stdlib imports detected!")
        return
    total_files = len(results)
    total_missing = sum(len(missing) for missing in results.values())
    print(f"\n{'=' * 40}")
    print(
        f" Found {total_missing} potentially missing import(s) in {total_files} file(s)"
    )
    print(f"{'=' * 40}\n")
    for path, missing in sorted(results.items()):
        rel_path = os.path.relpath(path)
        print(f"📄 {rel_path}")
        print(f"   {'─' * 40}")
        for name, suggestion in missing:
            print(f"   ⚠️  '{name}' used but not imported")
            print(f"   💡 Suggested: {suggestion}")
        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect potentially missing standard library imports in Python files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s .
  %(prog)s src/
  %(prog)s . --exclude tests
  %(prog)s . --exclude tests,docs
  %(prog)s . --show-all
        """,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--exclude",
        "-e",
        default="",
        help="Comma-separated list of directories to exclude",
    )
    parser.add_argument(
        "--show-all",
        "-a",
        action="store_true",
        help="Show all files even if no missing imports detected",
    )
    args = parser.parse_args()
    exclude_dirs = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".env",
        "build",
        "dist",
        "egg-info",
        ".tox",
        ".eggs",
    }
    if args.exclude:
        exclude_dirs.update(d.strip() for d in args.exclude.split(","))
    print(f"🔍 Checking for missing stdlib imports in: {args.directory}")
    results = scan_directory(args.directory, exclude_dirs)
    print_results(results)
    if args.show_all:
        print(f"\n{'=' * 40}")
        print(" All scanned files:")
        print(f"{'=' * 40}")
        root_path = Path(args.directory)
        for path in sorted(root_path.rglob("*.py")):
            if not any(excl in path.parts for excl in exclude_dirs):
                rel_path = os.path.relpath(path)
                status = "❌" if str(path) in results else "✅"
                print(f"  {status} {rel_path}")
    return 1 if results else 0


if __name__ == "__main__":
    raise SystemExit(main())
