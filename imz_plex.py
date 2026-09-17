#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import operator
import re
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path

from dh import STDLIB

SHEBANG_PATTERNS = [
    "#!/data/data/com.termux/files/usr/bin/python",
    "#!/usr/bin/env python",
    "#! */python",
]
COMPRESSED_EXTS = {
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".tar.bz2",
    ".tar.zst",
    ".zip",
    ".whl",
    ".7z",
}
PIP_LIST_PATH = Path("/sdcard/pip.txt")
KNOWN_PACKAGES = set()
STDLIB_MODULES = STDLIB


def load_known_packages() -> None:
    global KNOWN_PACKAGES
    if PIP_LIST_PATH.exists():
        try:
            with Path(PIP_LIST_PATH).open(encoding="utf-8") as f:
                KNOWN_PACKAGES = {
                    line.strip().split("==")[0].split(">")[0].split("<")[0].lower()
                    for line in f
                    if line.strip()
                }
        except Exception:
            pass


def is_python_file(path: Path | str) -> bool:
    path = Path(path)
    if not path.suffix or path.suffix == ".py":
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                for pattern in SHEBANG_PATTERNS:
                    if re.match(pattern, first_line):
                        return True
                content = f.read(1024)
                if re.search(r"\bimport\b|\bfrom\b\s+\w", content, re.IGNORECASE):
                    return True
        except:
            pass
        return False
    return path.suffix == ".py"


def extract_imports_from_ast(code: str):
    imports = set()
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0].lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0].lower())
    except:
        pass
    return imports


def extract_imports_regex(content: str):
    imports = set()
    patterns = [
        "^\\s*import\\s+(\\w+)",
        "^\\s*from\\s+(\\w+)\\s+import",
        "^\\s*import\\s+\\w+\\s+as\\s+\\w+",
    ]
    for line in content.splitlines():
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                pkg = match.group(1).split(".")[0].lower()
                imports.add(pkg)
    return imports


def get_imports_from_file(path: Path):
    try:
        content = Path(path).read_text(encoding="utf-8", errors="ignore")
        imports = extract_imports_from_ast(content)
        if not imports:
            imports = extract_imports_regex(content)
        return {imp for imp in imports if imp and imp != "from"}
    except:
        return set()


def handle_compressed_file(archive_path: Path):
    all_imports = defaultdict(int)
    path = Path(archive_path)
    try:
        if path.suffix in {".zip", ".whl"}:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if is_python_file(name):
                        content = zf.read(name).decode("utf-8", errors="ignore")
                        imports = extract_imports_from_ast(
                            content
                        ) or extract_imports_regex(content)
                        for imp in imports:
                            all_imports[imp] += 1
        elif path.suffix in {".tar.gz", ".tgz"}:
            with tarfile.open(path, "r:gz") as tf:
                for member in tf.getmembers():
                    if is_python_file(member.name) and not member.isdir():
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="ignore")
                            imports = extract_imports_from_ast(
                                content
                            ) or extract_imports_regex(content)
                            for imp in imports:
                                all_imports[imp] += 1
        elif path.suffix == ".tar.xz":
            with tarfile.open(path, "r:xz") as tf:
                for member in tf.getmembers():
                    if is_python_file(member.name) and not member.isdir():
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="ignore")
                            imports = extract_imports_from_ast(
                                content
                            ) or extract_imports_regex(content)
                            for imp in imports:
                                all_imports[imp] += 1
        elif path.suffix == ".tar.bz2":
            with tarfile.open(path, "r:bz2") as tf:
                for member in tf.getmembers():
                    if is_python_file(member.name) and not member.isdir():
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="ignore")
                            imports = extract_imports_from_ast(
                                content
                            ) or extract_imports_regex(content)
                            for imp in imports:
                                all_imports[imp] += 1
        elif path.suffix == ".tar.zst":
            try:
                import zstandard as zstd

                dctx = zstd.ZstdDecompressor()
                with (
                    Path(path).open("rb") as f,
                    dctx.stream_reader(f) as reader,
                    tarfile.open(fileobj=reader, mode="r") as tf,
                ):
                    for member in tf.getmembers():
                        if is_python_file(member.name) and not member.isdir():
                            f = tf.extractfile(member)
                            if f:
                                content = f.read().decode("utf-8", errors="ignore")
                                imports = extract_imports_from_ast(
                                    content
                                ) or extract_imports_regex(content)
                                for imp in imports:
                                    all_imports[imp] += 1
            except ImportError:
                pass
        elif path.suffix == ".7z":
            try:
                import subprocess

                result = subprocess.run(
                    ["7z", "l", str(path)], check=False, capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    ".py" in line or (
                        "python" in line.lower() and "bin" not in line.lower()
                    )
            except:
                pass
    except Exception:
        pass
    return dict(all_imports)


def walk_directory(root_path: str):
    all_imports = defaultdict(int)
    root = Path(root_path)
    for path in root.rglob("*"):
        try:
            if path.is_file() and is_python_file(path):
                imports = get_imports_from_file(path)
                for imp in imports:
                    all_imports[imp] += 1
            elif path.is_file() and path.suffix.lower() in COMPRESSED_EXTS:
                archive_imports = handle_compressed_file(path)
                for imp, count in archive_imports.items():
                    all_imports[imp] += count
        except Exception:
            continue
    return dict(all_imports)


def generate_requirements(imports_count) -> None:
    filtered = {
        pkg: count
        for pkg, count in imports_count.items()
        if pkg in KNOWN_PACKAGES and pkg not in STDLIB_MODULES
    }
    sorted_imports = sorted(filtered.items(), key=operator.itemgetter(1), reverse=True)
    with Path("requirements.txt").open("w", encoding="utf-8") as f:
        for pkg, count in sorted_imports:
            norm_pkg = pkg.replace("_", "-")
            if norm_pkg in {"numpy", "pandas", "matplotlib"}:
                f.write(f"{norm_pkg}\n")
            else:
                f.write(f"{norm_pkg}\n")
    print(
        f"Generated requirements.txt with {len(sorted_imports)} packages (stdlib excluded)"
    )
    print("Top 10 most used packages:")
    for pkg, count in sorted_imports[:10]:
        print(f"  {pkg}: {count} files")


def main() -> None:
    load_known_packages()
    print(f"Loaded {len(KNOWN_PACKAGES)} packages from pip.txt")
    print("Scanning current directory...")
    imports_count = walk_directory(".")
    print(
        f"Found {sum(imports_count.values())} total imports across {len(imports_count)} packages"
    )
    generate_requirements(imports_count)


if __name__ == "__main__":
    raise SystemExit(main())
