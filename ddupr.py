#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import hashlib
import sys
import tarfile
import textwrap
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from pathlib import Path

import brotlicffi as brotli
import lzma_mt
import zstandard as zstd
from loguru import logger

HAS_ZST = True
HAS_BR = True
ARCHIVE_EXTENSIONS = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".tgz",
    ".tbz2",
    ".zst",
    ".br",
}
UTILS_MAP: dict[str, str] = {
    "func": "funcs.py",
    "class": "classes.py",
    "const": "const.py",
}
CONSTANT_CALL_NAMES = {"TypeVar", "NewType", "ParamSpec", "TypeVarTuple"}


@dataclass
class PyObject:
    kind: str
    name: str
    source: str
    content_hash: str
    origin_file: str
    node_lineno: int
    node_end_lineno: int
    imports: list[str] = field(default_factory=list)


def _content_hash(source: str) -> str:
    normalised = "\n".join(
        line
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    return hashlib.sha256(normalised.encode()).hexdigest()


def _node_source(source: str, node: ast.AST) -> str:
    seg = ast.get_source_segment(source, node)
    if seg is not None:
        return seg
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    return textwrap.dedent("".join(lines[start:end]))


def _collect_imports(tree: ast.Module, node: ast.AST) -> list[str]:
    used: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            root = n
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
    lines: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                name = alias.asname or alias.name.split(".")[0]
                if name in used:
                    lines.append(ast.unparse(stmt))
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                name = alias.asname or alias.name
                if name in used:
                    lines.append(ast.unparse(stmt))
    return list(dict.fromkeys(lines))


def _is_constant_node(node: ast.AST) -> tuple[bool, str]:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
        return True, name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            return False, ""
        name = target.id
        if name.isupper():
            return True, name
        value = node.value
        if isinstance(value, ast.Call):
            func = value.func
            func_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if func_name in CONSTANT_CALL_NAMES:
                return True, name
    return False, ""


def analyse_source(source: str, origin: str) -> list[PyObject]:
    objects: list[PyObject] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.warning("Syntax error in {}: {}", origin, exc)
        return objects
    for node in tree.body:
        try:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                src = _node_source(source, node)
                objects.append(
                    PyObject(
                        kind="func",
                        name=node.name,
                        source=src,
                        content_hash=_content_hash(src),
                        origin_file=origin,
                        node_lineno=node.lineno,
                        node_end_lineno=node.end_lineno,
                        imports=_collect_imports(tree, node),
                    )
                )
            elif isinstance(node, ast.ClassDef):
                src = _node_source(source, node)
                objects.append(
                    PyObject(
                        kind="class",
                        name=node.name,
                        source=src,
                        content_hash=_content_hash(src),
                        origin_file=origin,
                        node_lineno=node.lineno,
                        node_end_lineno=node.end_lineno,
                        imports=_collect_imports(tree, node),
                    )
                )
            else:
                is_const, name = _is_constant_node(node)
                if is_const:
                    src = _node_source(source, node)
                    objects.append(
                        PyObject(
                            kind="const",
                            name=name,
                            source=src,
                            content_hash=_content_hash(src),
                            origin_file=origin,
                            node_lineno=node.lineno,
                            node_end_lineno=node.end_lineno,
                            imports=_collect_imports(tree, node),
                        )
                    )
        except Exception as exc:
            logger.error(
                "Failed to process node '{}' in {}: {}",
                getattr(node, "name", "?"),
                origin,
                exc,
            )
    return objects


def _read_zip(path: Path) -> list[tuple[str, str]]:
    results = []
    try:
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if not member.endswith(".py"):
                    continue
                try:
                    source = zf.read(member).decode("utf-8", errors="replace")
                    results.append((f"{path}::{member}", source))
                except Exception as exc:
                    logger.error("Cannot read {}::{}: {}", path, member, exc)
    except Exception as exc:
        logger.error("Cannot open zip {}: {}", path, exc)
    return results


def _read_tar(path: Path) -> list[tuple[str, str]]:
    results = []
    try:
        with tarfile.open(path) as tf:
            for member in tf.getmembers():
                if not member.name.endswith(".py") or not member.isfile():
                    continue
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    source = f.read().decode("utf-8", errors="replace")
                    results.append((f"{path}::{member.name}", source))
                except Exception as exc:
                    logger.error("Cannot read {}::{}: {}", path, member.name, exc)
    except Exception as exc:
        logger.error("Cannot open tar {}: {}", path, exc)
    return results


def _read_zst(path: Path) -> list[tuple[str, str]]:
    if not HAS_ZST:
        logger.warning("zstandard not installed; skipping {}", path)
        return []
    try:
        dctx = zstd.ZstdDecompressor()
        raw = dctx.decompress(path.read_bytes())
        source = raw.decode("utf-8", errors="replace")
        return [(str(path), source)]
    except Exception as exc:
        logger.error("Cannot decompress zst {}: {}", path, exc)
        return []


def _read_br(path: Path) -> list[tuple[str, str]]:
    if not HAS_BR:
        logger.warning("brotli not installed; skipping {}", path)
        return []
    try:
        raw = brotli.decompress(path.read_bytes())
        source = raw.decode("utf-8", errors="replace")
        return [(str(path), source)]
    except Exception as exc:
        logger.error("Cannot decompress brotli {}: {}", path, exc)
        return []


def _read_xz(path: Path) -> list[tuple[str, str]]:
    try:
        raw = lzma_mt.decompress(path.read_bytes(), threads=4)
        source = raw.decode("utf-8", errors="replace")
        return [(str(path), source)]
    except Exception as exc:
        logger.error("Cannot decompress brotli {}: {}", path, exc)
        return []


def read_file_sources(path: Path) -> list[tuple[str, str]]:
    ext = path.suffix.lower()
    if ext == ".py":
        try:
            return [(str(path), path.read_text(encoding="utf-8", errors="replace"))]
        except Exception as exc:
            logger.error("Cannot read {}: {}", path, exc)
            return []
    if ext == ".zip" or ext == ".whl":
        return _read_zip(path)
    if ext in {".tar", ".tgz", ".tbz2", ".tar.gz", ".tar.bz2", ".tar.xz"}:
        return _read_tar(path)
    if ext == ".xz":
        return _read_xz(path)
    if ext == ".zst":
        return _read_zst(path)
    if ext == ".br":
        return _read_br(path)
    return []


def _worker(path: Path) -> list[PyObject]:
    results: list[PyObject] = []
    for origin, source in read_file_sources(path):
        results.extend(analyse_source(source, origin))
    return results


def _build_utils_source(objects: list[PyObject]) -> str:
    all_imports: list[str] = []
    for obj in objects:
        all_imports.extend(obj.imports)
    unique_imports = list(dict.fromkeys(all_imports))
    parts: list[str] = []
    if unique_imports:
        parts.append("\n".join(unique_imports))
    for obj in objects:
        parts.append(obj.source.strip())
    return "\n\n\n".join(parts) + "\n"


def _validate_source(source: str, dest: Path) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError as exc:
        logger.error(
            "Generated source for {} has syntax error — skipping write: {}", dest, exc
        )
        return False


def write_utils(
    grouped: dict[str, list[PyObject]], utils_dir: Path, *, dry_run: bool = False
) -> dict[str, Path]:
    utils_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for kind, filename in UTILS_MAP.items():
        objects = grouped.get(kind, [])
        if not objects:
            continue
        dest = utils_dir / filename
        existing_hashes: set[str] = set()
        if dest.exists():
            try:
                existing_src = dest.read_text(encoding="utf-8")
                existing_tree = ast.parse(existing_src)
                for node in existing_tree.body:
                    seg = ast.get_source_segment(existing_src, node)
                    if seg:
                        existing_hashes.add(_content_hash(seg))
            except Exception as exc:
                logger.warning("Could not parse existing {}: {}", dest, exc)
        new_objects = [o for o in objects if o.content_hash not in existing_hashes]
        if not new_objects:
            print("No new objects for {} — skipping", dest)
            continue
        new_source = _build_utils_source(new_objects)
        if dest.exists():
            combined = dest.read_text(encoding="utf-8") + "\n\n" + new_source
        else:
            combined = '"""Auto-generated by refactor_utils.py"""\n\n' + new_source
        if not _validate_source(combined, dest):
            continue
        if not dry_run:
            dest.write_text(combined, encoding="utf-8")
            logger.success("Wrote {} object(s) to {}", len(new_objects), dest)
        else:
            print("[dry-run] Would write {} object(s) to {}", len(new_objects), dest)
        written[kind] = dest
    return written


def _build_import_line(utils_dir: Path, cwd: Path, kind: str) -> str:
    rel = utils_dir.relative_to(cwd)
    module_path = ".".join(rel.parts) + "." + UTILS_MAP[kind].removesuffix(".py")
    return f"from {module_path} import {{names}}"


def remove_and_patch(
    objects_to_remove: list[PyObject], utils_dir: Path, cwd: Path
) -> None:
    by_file: dict[str, list[PyObject]] = defaultdict(list)
    for obj in objects_to_remove:
        if "::" in obj.origin_file:
            logger.warning(
                "Cannot patch archive member {} — skipping move", obj.origin_file
            )
            continue
        by_file[obj.origin_file].append(obj)
    for path, objs in by_file.items():
        path = Path(path)
        if not path.exists():
            logger.warning("Origin file gone: {}", path)
            continue
        try:
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
        except Exception as exc:
            logger.error("Cannot read {} for patching: {}", path, exc)
            continue
        objs_sorted = sorted(objs, key=lambda o: o.node_lineno, reverse=True)
        patched_lines = list(lines)
        for obj in objs_sorted:
            start = obj.node_lineno - 1
            end = obj.node_end_lineno
            patched_lines[start:end] = []
        imports_by_kind: dict[str, list[str]] = defaultdict(list)
        for obj in objs:
            imports_by_kind[obj.kind].append(obj.name)
        import_lines: list[str] = []
        for kind, names in imports_by_kind.items():
            template = _build_import_line(utils_dir, cwd, kind)
            import_lines.append(template.format(names=", ".join(sorted(names))) + "\n")
        insert_at = 0
        try:
            tree = ast.parse("".join(patched_lines))
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    insert_at = node.end_lineno
        except SyntaxError:
            pass
        for i, imp in enumerate(import_lines):
            patched_lines.insert(insert_at + i, imp)
        new_source = "".join(patched_lines)
        if not _validate_source(new_source, path):
            logger.error("Patched {} has syntax errors — original preserved", path)
            continue
        try:
            path.write_text(new_source, encoding="utf-8")
            logger.success(
                "Patched {}: removed {} definition(s), added imports",
                path,
                len(objs),
            )
        except Exception as exc:
            logger.error("Cannot write patched {}: {}", path, exc)


def collect_all_paths(root: Path) -> list[Path]:
    all_exts = {".py"} | ARCHIVE_EXTENSIONS
    paths = [p for p in root.rglob("*") if p.suffix.lower() in all_exts and p.is_file()]
    utils_dir = root / "utils"
    return [p for p in paths if not str(p).startswith(str(utils_dir))]


def find_duplicates(
    all_objects: list[PyObject],
) -> tuple[dict[str, list[PyObject]], dict[str, list[PyObject]]]:
    by_hash: dict[str, list[PyObject]] = defaultdict(list)
    for obj in all_objects:
        by_hash[obj.content_hash].append(obj)
    duplicates = {h: objs for h, objs in by_hash.items() if len(objs) > 1}
    grouped: dict[str, list[PyObject]] = defaultdict(list)
    for objs in duplicates.values():
        representative = objs[0]
        grouped[representative.kind].append(representative)
    return duplicates, grouped


def run(cwd: Path, mode: str | None, workers: int) -> None:
    utils_dir = cwd / "utils"
    paths = collect_all_paths(cwd)
    print("Found {} file(s) to scan", len(paths))
    all_objects: list[PyObject] = []
    with Pool(processes=workers) as pool:
        for result in pool.imap_unordered(_worker, paths, chunksize=4):
            all_objects.extend(result)
    print("Extracted {} top-level object(s) total", len(all_objects))
    duplicates, grouped = find_duplicates(all_objects)
    sum(len(v) for v in grouped.values())
    print(
        "Found {} duplicate group(s): {} func, {} class, {} const",
        len(duplicates),
        len(grouped.get("func", [])),
        len(grouped.get("class", [])),
        len(grouped.get("const", [])),
    )
    if not duplicates:
        print("Nothing to do.")
        return
    if mode is None:
        for kind, objs in grouped.items():
            for obj in objs:
                print(
                    "[{}] '{}' duplicated in {} file(s)",
                    kind,
                    obj.name,
                    len(duplicates[obj.content_hash]),
                )
        return
    dry_run = mode not in {"copy", "move"}
    write_utils(grouped, utils_dir, dry_run=dry_run)
    if mode == "move":
        objects_to_remove: list[PyObject] = []
        for objs in duplicates.values():
            objects_to_remove.extend(objs[1:])
            objects_to_remove.append(objs[0])
        remove_and_patch(objects_to_remove, utils_dir, cwd)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract duplicate Python definitions into utils/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--copy",
        action="store_true",
        help="Copy duplicate definitions to utils/ (originals untouched)",
    )
    group.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Move duplicate definitions to utils/ and patch original files",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("."),
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, cpu_count() - 1),
        help="Number of worker processes (default: cpu_count - 1)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"],
        help="Loguru log level (default: INFO)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logger.remove()
    logger.add(
        sys.stderr,
        level=args.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        colorize=True,
    )
    logger.add(
        "refactor_utils.log",
        level="DEBUG",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
    )
    root = args.dir.resolve()
    if not root.is_dir():
        logger.error("'{}' is not a directory", root)
        sys.exit(1)
    mode = None
    if args.copy:
        mode = "copy"
    elif args.move:
        mode = "move"
    print(
        "Root: {}  |  mode: {}  |  workers: {}",
        root,
        mode or "report-only",
        args.workers,
    )
    run(root, mode, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
