#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import re
import tarfile
import zipfile
from multiprocessing import Pool, cpu_count
from pathlib import Path


class PIPPackageCache:
    def __init__(self, pip_list_path: str = "/sdcard/data/pip.txt"):
        self.packages = set()
        self.package_lower_map = {}
        self._load_pip_packages(pip_list_path)

    def _load_pip_packages(self, pip_list_path: str):
        if not os.path.exists(pip_list_path):
            print(f"⚠️  Warning: pip.txt not found at {pip_list_path}")
            print("   Script will still work but may include stdlib packages.")
            return
        try:
            with open(pip_list_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pkg_name = re.split(r"[=!<>;\[]", line)[0].strip()
                        if pkg_name:
                            self.packages.add(pkg_name.lower())
                            self.package_lower_map[pkg_name.lower()] = pkg_name
            print(f"✓ Loaded {len(self.packages)} packages from pip.txt")
        except Exception as e:
            print(f"⚠️  Error reading pip.txt: {e}")

    def is_available_on_pip(self, package_name: str) -> bool:
        return package_name.lower() in self.packages


def get_stdlib_modules() -> set[str]:
    import sys

    stdlib = set(sys.builtin_module_names)
    stdlib_modules = {
        "abc",
        "aifc",
        "argparse",
        "array",
        "ast",
        "asyncio",
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
        "pyexpat",
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
        "token",
        "tokenize",
        "trace",
        "traceback",
        "tracemalloc",
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
    }
    return stdlib | stdlib_modules


def extract_imports_from_code(code: str, path: str = "") -> set[str]:
    imports = set()
    import_pattern = r"^\s*import\s+([a-zA-Z0-9_\.\*\s,]+)"
    from_pattern = r"^\s*from\s+([a-zA-Z0-9_\.]+)\s+import"
    for line in code.split("\n"):
        line = line.split("#")[0].strip()
        import_match = re.match(import_pattern, line)
        if import_match:
            modules = import_match.group(1).split(",")
            for module in modules:
                module = module.strip().split()[0]
                if module and module != "*":
                    root = module.split(".")[0]
                    if root:
                        imports.add(root)
        from_match = re.match(from_pattern, line)
        if from_match:
            module = from_match.group(1).strip()
            if module != "__future__":
                root = module.split(".")[0]
                if root:
                    imports.add(root)
    return imports


def read_python_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️  Error reading {path}: {e}")
        return ""


def is_python_file(path: str) -> bool:
    if path.endswith(".py"):
        return True
    if "." not in Path(path).name:
        try:
            with open(path, "rb") as f:
                first_line = f.readline()
                return first_line.startswith(b"#!") and b"python" in first_line
        except:
            return False
    return False


def extract_from_zip(zip_path: str) -> set[str]:
    imports = set()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for file_info in zf.filelist:
                if file_info.filename.endswith(".py"):
                    try:
                        content = zf.read(file_info.filename).decode(
                            "utf-8", errors="ignore"
                        )
                        imports.update(
                            extract_imports_from_code(content, file_info.filename)
                        )
                    except Exception:
                        pass
    except Exception:
        pass
    return imports


def extract_from_tar(tar_path: str, compression: str | None = None) -> set[str]:
    imports = set()
    try:
        mode = f"r:{compression}" if compression else "r:*"
        with tarfile.open(tar_path, mode) as tf:
            for member in tf.getmembers():
                if member.name.endswith(".py") and member.isfile():
                    try:
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="ignore")
                            imports.update(
                                extract_imports_from_code(content, member.name)
                            )
                    except Exception:
                        pass
    except Exception:
        pass
    return imports


def process_file(path: str) -> set[str]:
    imports = set()
    try:
        if path.endswith((".zip", ".whl")):
            imports.update(extract_from_zip(path))
        elif path.endswith(".tar.gz"):
            imports.update(extract_from_tar(path, "gz"))
        elif path.endswith(".tar.xz"):
            imports.update(extract_from_tar(path, "xz"))
        elif path.endswith(".tar.zst"):
            imports.update(extract_from_tar(path, "zst"))
        elif path.endswith(".tar"):
            imports.update(extract_from_tar(path))
        elif is_python_file(path):
            content = read_python_file(path)
            imports.update(extract_imports_from_code(content, path))
    except Exception:
        pass
    return imports


def collect_files(root_dir: str, exclude_dirs: list[str] | None = None) -> list[str]:
    if exclude_dirs is None:
        exclude_dirs = {
            ".venv",
            "venv",
            ".env",
            "__pycache__",
            ".git",
            "node_modules",
            ".egg-info",
        }
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for filename in filenames:
            path = os.path.join(root, filename)
            if is_python_file(path) or filename.endswith(
                (".zip", ".whl", ".tar.gz", ".tar.xz", ".tar.zst", ".tar")
            ):
                files.append(path)
    return files


def filter_packages(
    imports: set[str],
    stdlib: set[str],
    pip_cache: PIPPackageCache,
    local_files: set[str],
) -> set[str]:
    filtered = set()
    for package in imports:
        pkg_lower = package.lower()
        if pkg_lower in stdlib:
            continue
        if package in local_files:
            continue
        if pip_cache.is_available_on_pip(package):
            actual_name = pip_cache.package_lower_map.get(pkg_lower, package)
            filtered.add(actual_name)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Generate requirements.txt by inspecting Python files recursively"
    )
    parser.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="requirements.txt",
        help="Output file path (default: requirements.txt)",
    )
    parser.add_argument(
        "-p",
        "--pip-list",
        default="/sdcard/data/pip.txt",
        help="Path to pip packages list (default: /sdcard/data/pip.txt)",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[
            ".venv",
            "venv",
            ".env",
            "__pycache__",
            ".git",
            "node_modules",
            ".egg-info",
        ],
        help="Directories to exclude from scan",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel jobs (default: {cpu_count()})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    print("-" * 40)
    print("📦 Requirements.txt Generator")
    print("-" * 40)
    print("\n📋 Loading pip packages database...")
    pip_cache = PIPPackageCache(args.pip_list)
    print("📚 Loading stdlib modules...")
    stdlib = get_stdlib_modules()
    print(f"✓ Loaded {len(stdlib)} stdlib modules")
    print(f"\n🔍 Scanning directory: {args.directory}")
    files = collect_files(args.directory, args.exclude)
    print(f"✓ Found {len(files)} Python files/archives")
    if not files:
        print("⚠️  No Python files found!")
        return
    if args.verbose:
        print("\nFiles found:")
        for f in files[:10]:
            print(f"  - {f}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")
    print(f"\n⚙️  Processing files ({args.jobs} workers)...")
    with Pool(args.jobs) as pool:
        results = pool.map(process_file, files)
    all_imports = set()
    for imports in results:
        all_imports.update(imports)
    print(f"✓ Found {len(all_imports)} unique imports")
    local_files = {Path(f).stem for f in files if is_python_file(f)}
    print("\n🔽 Filtering packages...")
    required_packages = filter_packages(all_imports, stdlib, pip_cache, local_files)
    print(f"✓ {len(required_packages)} external packages required")
    print(f"\n💾 Writing to {args.output}...")
    sorted_packages = sorted(required_packages, key=str.lower)
    with open(args.output, "w") as f:
        f.write("\n".join(sorted_packages) + "\n")
    print(f"✓ Successfully wrote {len(sorted_packages)} packages to {args.output}")
    print("\n" + "=" * 40)
    print("📋 Top packages found:")
    print("-" * 40)
    for pkg in sorted_packages[:20]:
        print(f"  • {pkg}")
    if len(sorted_packages) > 20:
        print(f"  ... and {len(sorted_packages) - 20} more")
    print("\n✅ Done!")


if __name__ == "__main__":
    raise SystemExit(main())
