#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import logging
import sys
import tarfile
import zipfile
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class PythonImportExtractor:
    def __init__(self, pip_packages_file: str = "/sdcard/data/pip.txt"):
        self.pip_packages = self._load_pip_packages(pip_packages_file)
        self.stdlib_modules = self._get_stdlib_modules()
        self.local_modules = set()

    @staticmethod
    def _get_stdlib_modules() -> set[str]:
        stdlib = set(sys.builtin_module_names)
        stdlib.update(
            {
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
                "dummy_thread",
                "dummy_threading",
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
                "formatter",
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
                "readline",
                "reprlib",
                "re",
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
                "__future__",
                "__main__",
                "graphlib",
                "tomllib",
                "zoneinfo",
            }
        )
        return stdlib

    @staticmethod
    def _load_pip_packages(pip_file: str) -> set[str]:
        try:
            pip_path = Path(pip_file)
            if not pip_path.exists():
                logger.warning(f"pip packages file not found: {pip_file}")
                return set()
            packages = set()
            with pip_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip().lower()
                    if line:
                        package_name = (
                            line.split("==")[0]
                            .split(">=")[0]
                            .split("<=")[0]
                            .split(">")[0]
                            .split("<")[0]
                            .split(";")[0]
                            .strip()
                        )
                        packages.add(package_name.replace("-", "_"))
                        packages.add(package_name.replace("_", "-"))
            print(f"Loaded {len(packages)} pip packages")
            return packages
        except Exception as e:
            logger.error(f"Error loading pip packages: {e}")
            return set()

    @staticmethod
    def _extract_imports_from_ast(code: str, filename: str = "<string>") -> set[str]:
        imports = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        imports.add(module_name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module.split(".")[0]
                    imports.add(module_name)
        except SyntaxError as e:
            logger.debug(f"Syntax error in {filename}: {e}")
        except Exception as e:
            logger.debug(f"Error parsing {filename}: {e}")
        return imports

    def _identify_local_modules(self, directory: str = ".") -> None:
        exclude_dirs = {".git", "__pycache__", ".pytest_cache", "dist", "build"}
        dir_path = Path(directory)
        for root_dir in [dir_path] + list(dir_path.rglob("*")):
            if not root_dir.is_dir() or root_dir.is_symlink():
                continue
            if root_dir.name in exclude_dirs:
                continue
            for item in root_dir.iterdir():
                if item.is_symlink():
                    continue
                if item.suffix in {".py", ".pyw"}:
                    module_name = item.stem
                    if module_name != "__init__":
                        self.local_modules.add(module_name)
                elif item.is_file() and item.suffix == "":
                    try:
                        with item.open("r", encoding="utf-8", errors="ignore") as f:
                            first_line = f.readline()
                            if first_line.startswith("#!") and "python" in first_line:
                                self.local_modules.add(item.name)
                    except:
                        pass

    def extract_from_file(self, path: Path) -> set[str]:
        try:
            code = path.read_text(encoding="utf-8", errors="ignore")
            return self._extract_imports_from_ast(code, str(path))
        except Exception as e:
            logger.debug(f"Error reading {path}: {e}")
            return set()

    def extract_from_zip(self, zippath: Path) -> set[str]:
        imports = set()
        try:
            with zipfile.ZipFile(zippath, "r") as zf:
                for info in zf.filelist:
                    if info.filename.endswith((".py", ".pyw")):
                        try:
                            code = zf.read(info.filename).decode(
                                "utf-8", errors="ignore"
                            )
                            imports.update(
                                self._extract_imports_from_ast(code, info.filename)
                            )
                        except Exception as e:
                            logger.debug(
                                f"Error reading {info.filename} from {zippath}: {e}"
                            )
        except Exception as e:
            logger.debug(f"Error processing zip {zippath}: {e}")
        return imports

    def extract_from_tar(self, tarpath: Path) -> set[str]:
        imports = set()
        try:
            with tarfile.open(tarpath, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.endswith((".py", ".pyw")) and member.isfile():
                        try:
                            f = tf.extractfile(member)
                            code = f.read().decode("utf-8", errors="ignore")
                            imports.update(
                                self._extract_imports_from_ast(code, member.name)
                            )
                        except Exception as e:
                            logger.debug(
                                f"Error reading {member.name} from {tarpath}: {e}"
                            )
        except Exception as e:
            logger.debug(f"Error processing tar {tarpath}: {e}")
        return imports

    def extract_from_whl(self, whlpath: Path) -> set[str]:
        return self.extract_from_zip(whlpath)

    def process_file(self, path: Path) -> set[str]:
        if path.suffix == ".zip" or path.suffix == ".whl":
            return self.extract_from_zip(path)
        elif path.suffixes[-2:] == [".tar", ".gz"] or path.name.endswith(
            (".tar.xz", ".tar.zst")
        ):
            return self.extract_from_tar(path)
        elif path.suffix in {".py", ".pyw"} or (path.is_file() and path.suffix == ""):
            return self.extract_from_file(path)
        return set()

    def filter_packages(self, imports: set[str]) -> set[str]:
        pip_packages = set()
        for imp in imports:
            imp_lower = imp.lower()
            if imp in self.stdlib_modules or imp_lower in self.stdlib_modules:
                continue
            if imp in self.local_modules or imp_lower in self.local_modules:
                continue
            if (
                imp_lower in self.pip_packages
                or imp.replace("_", "-") in self.pip_packages
            ):
                pip_packages.add(imp_lower)
        return pip_packages


def find_python_files(directory: str = ".") -> list[Path]:
    exclude_dirs = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
    }
    python_files = []
    dir_path = Path(directory)
    for item in dir_path.rglob("*"):
        if item.is_symlink():
            continue
        if item.is_dir() and item.name in exclude_dirs:
            continue
        if item.is_file():
            if item.suffix in {".py", ".pyw"}:
                python_files.append(item)
            elif item.suffix == "":
                try:
                    with item.open("r", encoding="utf-8", errors="ignore") as f:
                        first_line = f.readline()
                        if first_line.startswith("#!") and "python" in first_line:
                            python_files.append(item)
                except:
                    pass
            elif item.name.endswith((".zip", ".whl")) or item.name.endswith(
                (".tar.gz", ".tar.xz", ".tar.zst")
            ):
                python_files.append(item)
    return python_files


def process_single_file(
    args: tuple[Path, PythonImportExtractor],
) -> tuple[Path, set[str]]:
    path, extractor = args
    imports = extractor.process_file(path)
    filtered = extractor.filter_packages(imports)
    return (path, filtered)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Create requirements.txt by inspecting Python files"
    )
    parser.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="requirements.txt",
        help="Output file name (default: requirements.txt)",
    )
    parser.add_argument(
        "-p",
        "--pip-file",
        default="/sdcard/data/pip.txt",
        help="Path to pip packages file (default: /sdcard/data/pip.txt)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=cpu_count(),
        help=f"Number of worker processes (default: {cpu_count()})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    print(f"Scanning directory: {args.directory}")
    extractor = PythonImportExtractor(args.pip_file)
    print("Identifying local modules...")
    extractor._identify_local_modules(args.directory)
    print(f"Found {len(extractor.local_modules)} local modules")
    print("Finding Python files...")
    python_files = find_python_files(args.directory)
    print(f"Found {len(python_files)} Python files/archives")
    if not python_files:
        logger.warning("No Python files found")
        return
    print(f"Processing files with {args.workers} workers...")
    all_packages = defaultdict(set)
    with Pool(args.workers) as pool:
        results = pool.map(process_single_file, [(f, extractor) for f in python_files])
    for path, packages in results:
        for package in packages:
            all_packages[package].add(str(path))
    sorted_packages = sorted(all_packages.keys())
    print(f"Found {len(sorted_packages)} unique packages")
    output_path = Path(args.output)
    with output_path.open("w") as f:
        for package in sorted_packages:
            print(f" -  {package}")
            f.write(f"{package}\n")
    print(f"Requirements written to {args.output}")
    if args.verbose:
        print("\nPackages found:")
        for package in sorted_packages:
            sources = all_packages[package]
            print(f"  {package} (found in {len(sources)} file(s))")


if __name__ == "__main__":
    raise SystemExit(main())
