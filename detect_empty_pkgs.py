#!/data/data/com.termux/files/home/.local/bin/python
"""
Scan .tar.gz / .whl / .zip archives under the current directory (recursively)
and report (or, with -a/--apply, move) "empty" / "useless" ones into ./empty/ .

By default this is a DRY RUN: it prints what would be moved but changes
nothing.  Pass -a / --apply to actually move the archives.

Heuristics that flag an archive as useless:
  * invalid archive           – cannot be opened / truncated / not a tarball/zip
  * no files                  – archive contains only dirs / symlinks
  * no .py files              – nothing that could be a real package
  * only setup.py             – a lone setup.py with no code next to it
  * all non-setup .py empty   – every real .py file is 0 bytes / whitespace
  * only metadata             – README/LICENSE/PKG-INFO/pyproject.toml … only
  * only compiled files       – .pyc / __pycache__, no source
  * only docs/tests/examples  – no production code shipped
  * imports-only              – .py files parse but contain just imports,
                                docstrings or `pass`
  * too small                 – total uncompressed size below a threshold
"""

import argparse
import ast
import multiprocessing as mp
import shutil
import tarfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
WORKERS = 4  # fixed, per spec
MIN_ARCHIVE_BYTES = 300  # total uncompressed size below this = suspicious

# Archive formats we know how to open.  `.whl` is a zip file.
TARGET_GLOBS = ("*.tar.gz", "*.whl", "*.zip")

# Names that are "pure metadata", i.e. not actual shipped code.
METADATA_NAMES = {
    "PKG-INFO",
    "METADATA",
    "setup.cfg",
    "pyproject.toml",
    "setup.py",
    "MANIFEST.in",
    "requirements.txt",
    ".gitignore",
    ".gitattributes",
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "LICENSE.rst",
    "COPYING",
    "README",
    "README.md",
    "README.rst",
    "README.txt",
    "CHANGELOG",
    "CHANGELOG.md",
    "CHANGELOG.rst",
    "CHANGES",
    "CHANGES.md",
    "AUTHORS",
    "AUTHORS.md",
    "NOTICE",
    "TODO",
    "RECORD",
    "WHEEL",  # wheel-specific metadata
}

# Top-level directories that are not "real code".
NON_CODE_PREFIXES = (
    "docs/",
    "doc/",
    "examples/",
    "example/",
    "tests/",
    "test/",
    "testing/",
    "benchmarks/",
    "benchmark/",
)


# ---------------------------------------------------------------------------
# Uniform archive accessor  (tar.gz / zip / whl)
# ---------------------------------------------------------------------------
class _Member:
    """A single file inside an archive, with lazy content loading."""

    __slots__ = ("name", "size", "_read")

    def __init__(self, name, size, read):
        self.name = name
        self.size = size
        self._read = read

    def read(self) -> bytes:
        data = self._read()
        return data if data is not None else b""


class Archive:
    """Read-only, format-agnostic view over tar.gz / zip / whl archives."""

    def __init__(self, path: Path):
        self.path = path
        lower = path.name.lower()
        if lower.endswith(".tar.gz"):
            self.kind = "tar"
        elif lower.endswith((".zip", ".whl")):
            self.kind = "zip"
        else:
            raise ValueError(f"unsupported archive: {path}")
        self._fh = None

    def __enter__(self):
        if self.kind == "tar":
            self._fh = tarfile.open(self.path, "r:gz")
        else:
            self._fh = zipfile.ZipFile(self.path, "r")
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def files(self):
        """Yield _Member for every regular file in the archive."""
        fh = self._fh
        if self.kind == "tar":
            for m in fh.getmembers():
                if not m.isfile():
                    continue
                # bind m/fh into the closure so late binding doesn't break
                yield _Member(
                    m.name,
                    m.size,
                    lambda m=m, fh=fh: fh.extractfile(m).read(),
                )
        else:  # zip / whl
            for info in fh.infolist():
                if info.is_dir():
                    continue
                yield _Member(
                    info.filename,
                    info.file_size,
                    lambda n=info.filename, fh=fh: fh.read(n),
                )


# ---------------------------------------------------------------------------
# Small member helpers
# ---------------------------------------------------------------------------
def _is_py(member: _Member) -> bool:
    return member.name.endswith(".py")


def _basename(member: _Member) -> str:
    return member.name.replace("\\", "/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Individual checks.  Each returns a human-readable reason string if the
# archive should be moved, or None if this heuristic doesn't fire.
# ---------------------------------------------------------------------------
def _check_no_files(members):
    if not members:
        return "no files in archive"
    return None


def _check_no_py(members):
    if not any(_is_py(m) for m in members):
        return "no .py files"
    return None


def _check_only_setup_py(members):
    py = [m for m in members if _is_py(m)]
    if len(py) == 1 and _basename(py[0]) == "setup.py":
        return "only setup.py"
    return None


def _check_all_non_setup_empty(members):
    py = [m for m in members if _is_py(m)]
    non_setup = [m for m in py if _basename(m) != "setup.py"]
    if not non_setup:
        return None
    for m in non_setup:
        if m.read().strip():
            return None
    return "all non-setup .py files are empty"


def _check_only_metadata(members):
    """Every file is either a well-known metadata name, or an empty .py."""
    if not members:
        return None
    for m in members:
        base = _basename(m)
        if base in METADATA_NAMES:
            continue
        if _is_py(m) and not m.read().strip():
            continue
        return None
    return "only metadata files"


def _check_only_pyc(members):
    """No source, just compiled artifacts."""
    if any(_is_py(m) for m in members):
        return None
    has_compiled = any(
        m.name.endswith((".pyc", ".pyo")) or "__pycache__" in m.name for m in members
    )
    if has_compiled and all(
        m.name.endswith((".pyc", ".pyo")) or "__pycache__" in m.name for m in members
    ):
        return "only compiled Python files"
    return None


def _check_only_docs_tests(members):
    """Everything lives under docs/ tests/ examples/ … (plus top-level meta)."""
    if not members:
        return None
    for m in members:
        parts = m.name.split("/", 1)
        rel = parts[1] if len(parts) > 1 else parts[0]
        if rel.startswith(NON_CODE_PREFIXES):
            continue
        if "/" not in rel and rel in METADATA_NAMES:
            continue
        return None
    return "only docs/tests/examples"


def _py_is_trivial(src: str) -> bool:
    """True if a .py file only contains imports, docstrings, or `pass`."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue  # bare docstring / string literal
        return False
    return True


def _check_imports_only(members):
    """Every non-setup .py parses but contains only imports/docstrings/pass."""
    py = [m for m in members if _is_py(m)]
    if not py:
        return None
    saw_non_empty = False
    for m in py:
        if _basename(m) == "setup.py":
            continue
        src = m.read().decode("utf-8", "replace")
        if not src.strip():
            continue  # empty file, handled by another check
        if not _py_is_trivial(src):
            return None
        saw_non_empty = True
    if saw_non_empty:
        return "all .py files contain only imports/docstrings"
    return None


def _check_tiny(members):
    total = sum(m.size for m in members)
    if total < MIN_ARCHIVE_BYTES:
        return f"archive content too small ({total} bytes)"
    return None


# Order matters: cheaper / more definitive checks first.
_CHECKS = (
    _check_no_files,
    _check_no_py,
    _check_only_setup_py,
    _check_all_non_setup_empty,
    _check_only_metadata,
    _check_only_pyc,
    _check_only_docs_tests,
    _check_imports_only,
    _check_tiny,
)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def analyze(path: Path):
    """Return (path, reason_or_None).  Runs in a worker process."""
    try:
        with Archive(path) as ar:
            members = list(ar.files())
            for check in _CHECKS:
                reason = check(members)
                if reason:
                    return path, reason
            return path, None
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError, ValueError) as e:
        return path, f"invalid archive ({type(e).__name__})"


# ---------------------------------------------------------------------------
# Destination naming
# ---------------------------------------------------------------------------
def _split_archive_name(name: str):
    """Split 'foo.tar.gz' -> ('foo', '.tar.gz'); 'foo.whl' -> ('foo', '.whl')."""
    lower = name.lower()
    for compound in (".tar.gz",):
        if lower.endswith(compound):
            return name[: -len(compound)], name[-len(compound) :]
    p = Path(name)
    return p.stem, p.suffix


def _unique_dest(directory: Path, name: str) -> Path:
    """Avoid clobbering existing files in the destination directory."""
    dest = directory / name
    if not dest.exists():
        return dest
    stem, suffix = _split_archive_name(name)
    i = 1
    while True:
        dest = directory / f"{stem}.{i}{suffix}"
        if not dest.exists():
            return dest
        i += 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Find empty/useless .tar.gz / .whl / .zip Python packages and "
            "(optionally) move them into ./empty/ ."
        ),
    )
    ap.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="actually move the archives (default is dry-run)",
    )
    return ap.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    cwd = Path.cwd()
    empty_dir = cwd / "empty"

    # Only create ./empty/ when we're going to use it.
    if args.apply:
        empty_dir.mkdir(exist_ok=True)

    # Collect targets across all supported extensions.
    targets = sorted(
        {
            p
            for pattern in TARGET_GLOBS
            for p in cwd.rglob(pattern)
            if p.is_file() and empty_dir not in p.parents
        }
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] scanning {len(targets)} archive(s) with {WORKERS} workers\n")

    matched = 0
    moved = 0

    with mp.Pool(WORKERS) as pool:
        # chunksize=1 gives the best load-balancing for uneven work
        for path, reason in pool.imap_unordered(analyze, targets, chunksize=1):
            if reason is None:
                continue
            matched += 1

            rel = path.relative_to(cwd)
            if not args.apply:
                print(f"WOULD MOVE  [{reason}]  {rel}")
                continue

            dest = _unique_dest(empty_dir, path.name)
            try:
                shutil.move(str(path), str(dest))
            except OSError as e:
                print(f"! failed to move {rel}: {e}")
                continue
            moved += 1
            print(f"MOVED  [{reason}]  {rel}  ->  empty/{dest.name}")

    print()
    if args.apply:
        print(f"Moved {moved} of {len(targets)} archives into {empty_dir}")
    else:
        print(
            f"Dry run: {matched} of {len(targets)} archives would be moved. "
            f"Re-run with -a / --apply to do it."
        )


if __name__ == "__main__":
    main()
