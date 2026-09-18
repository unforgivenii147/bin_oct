#!/data/data/com.termux/files/home/.local/bin/python
"""
pydedup.py — Find duplicate top-level Python definitions and consolidate them.

Subcommands
-----------
    report   Show duplicates without modifying anything.
    copy     Copy one representative of each duplicate group into utils/.
    move     Copy into utils/ and patch the originals with imports.

Behavioral mapping to the original scripts
------------------------------------------
    ddup.py      ->  pydedup.py copy --func-file func.py --class-file class.py --const-file const.py
                     pydedup.py move --func-file func.py --class-file class.py --const-file const.py

    ddupr.py     ->  pydedup.py report
                     pydedup.py copy
                     pydedup.py move

    dduputil.py  ->  pydedup.py copy --min-occurs 2 --workers N
                     pydedup.py move --min-occurs 2 --workers N

    vddup.py     ->  pydedup.py copy --func-file functions.py \
                                    --class-file classes.py \
                                    --const-file constants.py

    vddup2.py    ->  pydedup.py copy --match-mode name --no-archives --const-mode all

Third-party dependencies (all optional; the script degrades gracefully):
    loguru            pretty logging (falls back to stdlib logging)
    zstandard         .zst decompression
    brotli / brotlicffi  .br decompression
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------
import argparse
import ast
import bz2
import gzip
import hashlib
import lzma
import sys
import tarfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Iterable, Iterator, Optional

# ---------------------------------------------------------------------------
# Optional third-party dependencies (degrade gracefully if missing)
# ---------------------------------------------------------------------------
try:
    from loguru import logger
    _HAS_LOGURU = True
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("pydedup")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _HAS_LOGURU = False

try:
    import zstandard as zstd  # type: ignore
    _HAS_ZSTD = True
except ImportError:
    zstd = None  # type: ignore
    _HAS_ZSTD = False

try:
    import brotli  # type: ignore
    _HAS_BROTLI = True
except ImportError:
    try:
        import brotlicffi as brotli  # type: ignore
        _HAS_BROTLI = True
    except ImportError:
        brotli = None  # type: ignore
        _HAS_BROTLI = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARCHIVE_SUFFIXES = (
    ".zip", ".whl",
    ".tar", ".tar.gz", ".tar.bz2", ".tar.xz",
    ".tgz", ".tbz2", ".txz",
)
COMPRESSED_SUFFIXES = (".gz", ".bz2", ".xz", ".lzma", ".zst", ".br")
PYTHON_SUFFIX = ".py"

KIND_ORDER = ("func", "class", "const")
KIND_TO_FILE_DEFAULT = {"func": "funcs.py", "class": "classes.py", "const": "const.py"}

# Assignments whose RHS is a call to one of these names are treated as
# constants even if the target name is not upper-case.
TYPEVAR_NAMES = {"TypeVar", "NewType", "ParamSpec", "TypeVarTuple"}

# Directories that are always skipped during the scan.
SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Source:
    """A unit of Python source text (from a file, an archive member, or a decompressed stream)."""
    origin: str                    # human-readable identifier (path or archive::member)
    text: str                      # decoded source
    path: Optional[Path] = None    # on-disk path if patchable, else None


@dataclass
class Definition:
    """A single top-level function, class or constant."""
    kind: str                      # 'func' | 'class' | 'const'
    name: str
    source: str                    # normalized source (ast.unparse output)
    content_hash: str
    origin: str
    lineno: int
    end_lineno: int
    imports: list[str] = field(default_factory=list)
    path: Optional[Path] = None    # None for archive/compressed members


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
def _success(msg: str, *args) -> None:
    """Emit a SUCCESS-level message (works with or without loguru)."""
    if _HAS_LOGURU:
        logger.success(msg, *args)
    else:
        logger.info(msg, *args)


def _setup_logging(level: str, verbose: bool) -> None:
    """Configure loguru if available, otherwise stdlib logging."""
    lvl = "DEBUG" if verbose else level.upper()
    if _HAS_LOGURU:
        logger.remove()
        logger.add(
            sys.stderr,
            level=lvl,
            format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
            colorize=True,
        )
        logger.add("pydedup.log", level="DEBUG", rotation="5 MB", retention=3, encoding="utf-8")
    else:
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        logging.getLogger().setLevel(lvl if lvl in valid else "INFO")


# ---------------------------------------------------------------------------
# Scanning — file / archive / compressed sources
# ---------------------------------------------------------------------------
def _safe_read_text(path: Path) -> Optional[str]:
    """Read *path* as UTF-8 (falling back to latin-1). Returns None on OSError."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except OSError as exc:
            logger.error(f"cannot read {path}: {exc}")
            return None
    except OSError as exc:
        logger.error(f"cannot read {path}: {exc}")
        return None


def _decompress(path: Path) -> Optional[bytes]:
    """Decompress a single-file compressed stream based on its suffix."""
    suffix = path.suffix.lower()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.error(f"cannot read {path}: {exc}")
        return None
    try:
        if suffix == ".gz":
            return gzip.decompress(raw)
        if suffix == ".bz2":
            return bz2.decompress(raw)
        if suffix in (".xz", ".lzma"):
            return lzma.decompress(raw)
        if suffix == ".zst":
            if not _HAS_ZSTD:
                logger.warning(f"zstandard not installed; skipping {path}")
                return None
            return zstd.ZstdDecompressor().decompress(raw)
        if suffix == ".br":
            if not _HAS_BROTLI:
                logger.warning(f"brotli not installed; skipping {path}")
                return None
            return brotli.decompress(raw)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"decompression failed for {path}: {exc}")
    return None


def _iter_zip(path: Path) -> Iterator[Source]:
    """Yield Python source for every .py member of a zip/whl archive."""
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.lower().endswith(PYTHON_SUFFIX):
                    continue
                try:
                    raw = zf.read(info)
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"cannot read {path}::{info.filename}: {exc}")
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                yield Source(origin=f"{path}::{info.filename}", text=text, path=None)
    except (zipfile.BadZipFile, OSError) as exc:
        logger.error(f"cannot open zip {path}: {exc}")


def _iter_tar(path: Path) -> Iterator[Source]:
    """Yield Python source for every .py member of a tar family archive."""
    try:
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile() or not member.name.lower().endswith(PYTHON_SUFFIX):
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                try:
                    raw = fh.read()
                finally:
                    fh.close()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                yield Source(origin=f"{path}::{member.name}", text=text, path=None)
    except (tarfile.TarError, OSError) as exc:
        logger.error(f"cannot open tar {path}: {exc}")


def _iter_compressed(path: Path) -> Iterator[Source]:
    """Yield a Source for a single-file compressed Python file (.py.gz etc.)."""
    raw = _decompress(path)
    if raw is None:
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    # Heuristic: only treat as Python if the name hints at it or the body looks Pythonic.
    if ".py" in path.name or "def " in text or "class " in text:
        yield Source(origin=str(path), text=text, path=None)


def iter_sources(root: Path, include_archives: bool = True) -> Iterator[Source]:
    """Walk *root* and yield every :class:`Source` we can find.

    The ``utils/`` output directory is skipped, as are common junk
    directories (``.git``, ``__pycache__``, virtualenvs, …).
    """
    root = root.resolve()
    utils_dir = (root / "utils").resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        # Skip anything under <root>/utils/
        try:
            resolved.relative_to(utils_dir)
            continue
        except ValueError:
            pass
        # Skip junk dirs
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue

        name_lower = path.name.lower()
        if name_lower.endswith(PYTHON_SUFFIX):
            text = _safe_read_text(path)
            if text is not None:
                yield Source(origin=str(path), text=text, path=path)
            continue

        if not include_archives:
            continue

        full_suffixes = "".join(path.suffixes).lower()
        if full_suffixes.endswith((".zip", ".whl")):
            yield from _iter_zip(path)
        elif full_suffixes.endswith(
            (".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")
        ):
            yield from _iter_tar(path)
        elif full_suffixes.endswith(COMPRESSED_SUFFIXES):
            yield from _iter_compressed(path)


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------
def _sha256(text: str) -> str:
    """Return the hex sha256 of *text* (utf-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _collect_imports(tree: ast.Module, node: ast.AST) -> list[str]:
    """Return the source of top-level import statements referenced by *node*."""
    used: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            used.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            cur = sub
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                used.add(cur.id)

    result: list[str] = []
    seen: set[str] = set()
    for top in tree.body:
        if isinstance(top, ast.Import):
            if any((a.asname or a.name.split(".")[0]) in used for a in top.names):
                stmt = ast.unparse(top)
                if stmt not in seen:
                    seen.add(stmt)
                    result.append(stmt)
        elif isinstance(top, ast.ImportFrom):
            if any((a.asname or a.name) in used for a in top.names):
                stmt = ast.unparse(top)
                if stmt not in seen:
                    seen.add(stmt)
                    result.append(stmt)
    return result


def _is_literal_value(node: ast.AST) -> bool:
    """True if *node* is a literal constant / tuple / list / set / dict of literals."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_value(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            _is_literal_value(k) and _is_literal_value(v)
            for k, v in zip(node.keys, node.values)
        )
    return False


def _is_typevar_call(node: ast.Assign) -> bool:
    """True if the RHS is a call like ``TypeVar(...)`` / ``NewType(...)``."""
    value = node.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id in TYPEVAR_NAMES
    if isinstance(func, ast.Attribute):
        return func.attr in TYPEVAR_NAMES
    return False


def _const_names(node: ast.AST, mode: str) -> list[str]:
    """Return the target names of a top-level const node, or [] if not a const.

    ``mode``:
        * ``"all"``       — any ``Assign`` with simple name / tuple targets
        * ``"uppercase"`` — name is ALL_CAPS, or the RHS is a TypeVar-like call
        * ``"literal"``   — RHS is a literal (str/num/tuple/list/dict of literals)
    """
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names = [node.target.id]
    elif isinstance(node, ast.Assign):
        names = []
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.append(t.id)
            elif isinstance(t, ast.Tuple):
                names.extend(e.id for e in t.elts if isinstance(e, ast.Name))
    else:
        return []
    if not names:
        return []

    if mode == "uppercase":
        if not all(n.isupper() for n in names):
            if not (isinstance(node, ast.Assign) and _is_typevar_call(node)):
                return []
    elif mode == "literal":
        if not (isinstance(node, ast.Assign) and _is_literal_value(node.value)):
            return []
    return names


def extract_definitions(
    text: str,
    origin: str,
    path: Optional[Path],
    const_mode: str = "all",
) -> list[Definition]:
    """Parse *text* and return every top-level definition it contains."""
    try:
        tree = ast.parse(text, filename=origin)
    except SyntaxError as exc:
        logger.warning(f"syntax error in {origin}: {exc}")
        return []

    out: list[Definition] = []
    for node in tree.body:
        kind: Optional[str] = None
        name = ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind, name = "func", node.name
        elif isinstance(node, ast.ClassDef):
            kind, name = "class", node.name
        else:
            names = _const_names(node, const_mode)
            if names:
                kind, name = "const", names[0]
        if kind is None:
            continue
        try:
            src = ast.unparse(node)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"unparse failed in {origin} for {name}: {exc}")
            continue
        out.append(
            Definition(
                kind=kind,
                name=name,
                source=src,
                content_hash=_sha256(src),
                origin=origin,
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                imports=_collect_imports(tree, node),
                path=path,
            )
        )
    return out


def _worker(payload: tuple[str, str, Optional[Path], str]) -> list[Definition]:
    """Multiprocessing entry point: unpack and delegate to :func:`extract_definitions`."""
    text, origin, path, const_mode = payload
    return extract_definitions(text, origin, path, const_mode)


def _collect_all(
    sources: list[Source],
    workers: int,
    const_mode: str,
) -> list[Definition]:
    """Run :func:`extract_definitions` over all sources, optionally in parallel."""
    payloads = [(s.text, s.origin, s.path, const_mode) for s in sources]
    if workers <= 1:
        out: list[Definition] = []
        for p in payloads:
            out.extend(_worker(p))
        return out
    with Pool(processes=workers) as pool:
        results = pool.map(_worker, payloads, chunksize=4)
    out = []
    for r in results:
        out.extend(r)
    return out


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------
def group_duplicates(
    defs: Iterable[Definition],
    min_occurs: int = 2,
    match_mode: str = "content",
) -> dict[str, list[Definition]]:
    """Group definitions by content hash (default) or by kind+name, keeping only groups >= *min_occurs*."""
    groups: dict[str, list[Definition]] = defaultdict(list)
    for d in defs:
        key = f"{d.kind}::{d.name}" if match_mode == "name" else d.content_hash
        groups[key].append(d)
    return {k: v for k, v in groups.items() if len(v) >= min_occurs}


# ---------------------------------------------------------------------------
# Writing to utils/
# ---------------------------------------------------------------------------
def _read_existing_hashes(path: Path) -> set[str]:
    """Return the set of content hashes already present in *path* (empty if missing/unparsable)."""
    if not path.exists():
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"cannot parse {path}: {exc}")
        return set()
    hashes: set[str] = set()
    for node in tree.body:
        try:
            hashes.add(_sha256(ast.unparse(node)))
        except Exception:  # noqa: BLE001
            continue
    return hashes


def write_utils(
    groups: dict[str, list[Definition]],
    utils_dir: Path,
    func_file: str,
    class_file: str,
    const_file: str,
    dry_run: bool = False,
) -> dict[str, Path]:
    """Append one representative of every duplicate group into the relevant utils/*.py file."""
    utils_dir.mkdir(parents=True, exist_ok=True)
    file_map = {"func": func_file, "class": class_file, "const": const_file}
    by_kind: dict[str, list[Definition]] = defaultdict(list)
    for group in groups.values():
        by_kind[group[0].kind].append(group[0])

    written: dict[str, Path] = {}
    for kind in KIND_ORDER:
        reps = by_kind.get(kind, [])
        if not reps:
            continue
        target = utils_dir / file_map[kind]
        existing = _read_existing_hashes(target)
        new_reps = [r for r in reps if r.content_hash not in existing]
        if not new_reps:
            logger.info(f"no new objects for {target}")
            continue

        # Avoid name collisions inside the same generated file.
        deduped: list[Definition] = []
        seen_names: set[str] = set()
        for r in new_reps:
            if r.name in seen_names:
                logger.warning(f"name collision in {target.name}: '{r.name}' — skipping")
                continue
            seen_names.add(r.name)
            deduped.append(r)
        if not deduped:
            continue

        # Collect imports for a fresh file, deduped in order.
        if not (target.exists() and target.stat().st_size > 0):
            imports: list[str] = []
            for r in deduped:
                imports.extend(r.imports)
            seen_imports: set[str] = set()
            uniq_imports: list[str] = []
            for imp in imports:
                if imp not in seen_imports:
                    seen_imports.add(imp)
                    uniq_imports.append(imp)

        if target.exists() and target.stat().st_size > 0:
            base = target.read_text(encoding="utf-8").rstrip() + "\n\n"
        else:
            base = '"""Auto-generated by pydedup."""\n\n'
            if uniq_imports:
                base += "\n".join(uniq_imports) + "\n\n"

        body = "\n\n".join(r.source for r in deduped) + "\n"
        text = base + body

        try:
            ast.parse(text)
        except SyntaxError as exc:
            logger.error(f"generated {target} has syntax errors — skipping: {exc}")
            continue

        if dry_run:
            logger.info(f"[dry-run] would write {len(deduped)} object(s) to {target}")
        else:
            target.write_text(text, encoding="utf-8")
            _success(f"wrote {len(deduped)} object(s) to {target}")
        written[kind] = target
    return written


# ---------------------------------------------------------------------------
# Patching originals on 'move'
# ---------------------------------------------------------------------------
def _insert_imports(lines: list[str], imports: list[str]) -> list[str]:
    """Insert *imports* after the module docstring and any existing imports."""
    if not imports:
        return lines
    text = "".join(lines)
    insert_at = 0
    try:
        tree = ast.parse(text)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            insert_at = tree.body[0].end_lineno or tree.body[0].lineno
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                insert_at = max(insert_at, node.end_lineno or node.lineno)
    except SyntaxError:
        return imports + lines
    return lines[:insert_at] + imports + lines[insert_at:]


def _patch_file(
    path: Path,
    defs: list[Definition],
    utils_rel: Path,
    file_map: dict[str, str],
    dry_run: bool,
) -> None:
    """Remove *defs* from *path* and inject imports from the corresponding utils module."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(f"cannot read {path}: {exc}")
        return

    lines = text.splitlines(keepends=True)
    # Remove definitions from bottom to top so line numbers stay valid.
    for d in sorted(defs, key=lambda x: x.lineno, reverse=True):
        start = d.lineno - 1
        end = d.end_lineno
        if start < 0 or end > len(lines) or start >= end:
            logger.warning(f"invalid line range for '{d.name}' in {path}")
            continue
        del lines[start:end]

    # Build one import per kind.
    names_by_kind: dict[str, list[str]] = defaultdict(list)
    for d in defs:
        names_by_kind[d.kind].append(d.name)

    import_lines: list[str] = []
    for kind in KIND_ORDER:
        names = names_by_kind.get(kind)
        if not names:
            continue
        module = file_map[kind].removesuffix(".py")
        full_module = ".".join(list(utils_rel.parts) + [module])
        names_sorted = ", ".join(sorted(set(names)))
        import_lines.append(f"from {full_module} import {names_sorted}\n")

    patched = _insert_imports(lines, import_lines)
    new_text = "".join(patched)

    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        logger.error(f"patched {path} has syntax errors — original preserved: {exc}")
        return

    if dry_run:
        logger.info(f"[dry-run] would patch {path}: -{len(defs)} definition(s), +imports")
    else:
        path.write_text(new_text, encoding="utf-8")
        _success(f"patched {path}: -{len(defs)} definition(s)")


def patch_originals(
    groups: dict[str, list[Definition]],
    utils_dir: Path,
    root: Path,
    func_file: str,
    class_file: str,
    const_file: str,
    dry_run: bool = False,
) -> None:
    """Remove moved definitions from every patchable origin file and add imports."""
    try:
        utils_rel = utils_dir.relative_to(root)
    except ValueError:
        utils_rel = Path("utils")

    file_map = {"func": func_file, "class": class_file, "const": const_file}

    by_file: dict[Path, list[Definition]] = defaultdict(list)
    for group in groups.values():
        for d in group:
            if d.path is None:
                logger.warning(f"cannot patch archive/compressed member {d.origin}")
                continue
            by_file[d.path].append(d)

    for path, defs in by_file.items():
        _patch_file(path, defs, utils_rel, file_map, dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_common_args(p: argparse.ArgumentParser) -> None:
    """Add the flags shared by every subcommand."""
    p.add_argument(
        "--dir", type=Path, default=Path("."),
        help="root directory to scan (default: current directory)",
    )
    p.add_argument(
        "--workers", type=int, default=max(1, cpu_count() - 1),
        help="number of worker processes (default: cpu_count-1)",
    )
    p.add_argument(
        "--min-occurs", type=int, default=2,
        help="minimum occurrences to count as duplicate (default: 2)",
    )
    p.add_argument(
        "--match-mode", choices=("content", "name"), default="content",
        help="how to decide duplicates (default: content)",
    )
    p.add_argument(
        "--const-mode", choices=("all", "uppercase", "literal"), default="all",
        help="which top-level Assign nodes count as constants (default: all)",
    )
    p.add_argument(
        "--no-archives", action="store_true",
        help="do not scan zip/tar archives or compressed files",
    )
    p.add_argument(
        "--utils-dir", type=Path, default=None,
        help="output directory (default: <root>/utils)",
    )
    p.add_argument(
        "--func-file", default="funcs.py",
        help="file name for functions inside utils/ (default: funcs.py)",
    )
    p.add_argument(
        "--class-file", default="classes.py",
        help="file name for classes inside utils/ (default: classes.py)",
    )
    p.add_argument(
        "--const-file", default="const.py",
        help="file name for constants inside utils/ (default: const.py)",
