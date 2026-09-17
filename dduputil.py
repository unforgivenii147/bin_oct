#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import hashlib
import sys
import tempfile
from ast import Name, expr
from collections.abc import Iterable
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path

from loguru import logger

try:
    import bz2
    import gzip
    import lzma
    import tarfile
    import zipfile
except Exception:
    logger.exception("missing builtin archive modules (unexpected)")
HAS_ZSTD = True
try:
    import zstandard as zstd
except Exception:
    HAS_ZSTD = False
HAS_BROTLI = True
try:
    import brotli
except Exception:
    HAS_BROTLI = False
RECOGNIZED_ARCHIVE_EXTS = {
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
}
SINGLE_COMPRESSED = {".gz", ".bz2", ".xz", ".zst", ".br"}
PY_EXT = ".py"
UTILS_DIR = Path("utils")
FUNC_FILE = UTILS_DIR / "funcs.py"
CLASS_FILE = UTILS_DIR / "classes.py"
CONST_FILE = UTILS_DIR / "const.py"


@dataclass
class SourceFile:
    path: Path
    relpath: Path
    text: str
    origin: str


@dataclass
class Extracted:
    kind: str
    name: str
    node: ast.AST
    src_text: str
    file: SourceFile
    imports: list[ast.stmt]


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def node_to_code(node: ast.AST) -> str:
    return ast.unparse(node) + "\n"


def is_constant_assign(node: ast.Assign) -> bool:
    if not isinstance(node, ast.Assign):
        return False

    def target_ok(t: Name | tuple) -> bool:
        return isinstance(t, ast.Name)

    if any(
        not target_ok(t) for t in node.targets if isinstance(t, (ast.Name, ast.Tuple))
    ):
        return False

    def lit_ok(n: expr | None) -> bool:
        if isinstance(n, ast.Constant):
            return True
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            return all(lit_ok(e) for e in n.elts)
        if isinstance(n, ast.Dict):
            return all(
                lit_ok(k) and lit_ok(v) for k, v in zip(n.keys, n.values, strict=False)
            )
        return False

    return lit_ok(node.value)


def extract_top_level_imports(tree: ast.Module) -> list[ast.stmt]:
    return [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def try_decompress_single(data: bytes, ext: str) -> tuple[bytes, str] | None:
    try:
        if ext == ".gz":
            return gzip.decompress(data), ""
        if ext == ".bz2":
            return bz2.decompress(data), ""
        if ext == ".xz":
            return lzma.decompress(data), ""
        if ext == ".zst":
            if not HAS_ZSTD:
                raise RuntimeError("zstandard library not installed")
            dctx = zstd.ZstdDecompressor()
            return dctx.decompress(data), ""
        if ext == ".br":
            if not HAS_BROTLI:
                raise RuntimeError("brotli library not installed")
            return brotli.decompress(data), ""
    except Exception as e:
        logger.debug("decompression failed for ext {}: {}", ext, e)
    return None


def iter_python_sources(root: Path) -> Iterable[SourceFile]:
    root = root.resolve()
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        "".join(p.suffixes) or p.suffix
        lower = str(p.name).lower()
        try:
            if lower.endswith(".py"):
                try:
                    text = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = p.read_text(encoding="latin-1")
                yield SourceFile(
                    path=p, relpath=p.relative_to(root), text=text, origin=str(p)
                )
                continue
            if any(lower.endswith(ext) for ext in RECOGNIZED_ARCHIVE_EXTS):
                if lower.endswith(".zip"):
                    try:
                        with zipfile.ZipFile(p, "r") as z:
                            for zi in z.infolist():
                                if zi.is_dir():
                                    continue
                                name = zi.filename
                                if not name.lower().endswith(".py"):
                                    continue
                                data = z.read(zi)
                                try:
                                    text = data.decode("utf-8")
                                except UnicodeDecodeError:
                                    text = data.decode("latin-1")
                                virtual_path = Path(p.name) / Path(name)
                                yield SourceFile(
                                    path=p,
                                    relpath=virtual_path,
                                    text=text,
                                    origin=f"{p}:{name}",
                                )
                    except Exception as e:
                        logger.error("error reading zip {}: {}", p, e)
                else:
                    try:
                        with tarfile.open(p, "r:*") as t:
                            for ti in t.getmembers():
                                if not ti.isfile():
                                    continue
                                name = ti.name
                                if not name.lower().endswith(".py"):
                                    continue
                                f = t.extractfile(ti)
                                if not f:
                                    continue
                                data = f.read()
                                try:
                                    text = data.decode("utf-8")
                                except UnicodeDecodeError:
                                    text = data.decode("latin-1")
                                virtual_path = Path(p.name) / Path(name)
                                yield SourceFile(
                                    path=p,
                                    relpath=virtual_path,
                                    text=text,
                                    origin=f"{p}:{name}",
                                )
                    except Exception as e:
                        logger.error("error reading tar {}: {}", p, e)
                continue
            for ext in SINGLE_COMPRESSED:
                if lower.endswith(ext):
                    try:
                        data = p.read_bytes()
                        dec = try_decompress_single(data, ext.lstrip("."))
                        if dec:
                            bytes_decomp, _suggested = dec
                            try:
                                txt = bytes_decomp.decode("utf-8")
                            except UnicodeDecodeError:
                                txt = bytes_decomp.decode("latin-1")
                            if ".py" in p.name or ("def " in txt or "class " in txt):
                                virtual = Path(p.name).with_suffix("")
                                yield SourceFile(
                                    path=p,
                                    relpath=virtual,
                                    text=txt,
                                    origin=f"{p}:{p.name}",
                                )
                    except Exception as e:
                        logger.debug("decompress attempt failed for {}: {}", p, e)
                    break
        except Exception as exc:
            logger.exception("error iterating {}: {}", p, exc)


def extract_defs_from_source(
    srcfile: tuple[str, str, str, str],
) -> tuple[str, list[dict]]:
    path_str, _relpath_str, text, origin = srcfile
    results = []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        logger.error("Syntax error parsing {}: {}:{}", origin, e.lineno, e.msg)
        return path_str, results
    imports = extract_top_level_imports(tree)
    for node in tree.body:
        try:
            if isinstance(node, ast.FunctionDef):
                if node.name == "main":
                    continue
                code = node_to_code(node)
                h = sha256_text(code)
                results.append(
                    {
                        "kind": "func",
                        "name": node.name,
                        "hash": h,
                        "code": code,
                        "imports": imports,
                    }
                )
            elif isinstance(node, ast.ClassDef):
                code = node_to_code(node)
                h = sha256_text(code)
                results.append(
                    {
                        "kind": "class",
                        "name": node.name,
                        "hash": h,
                        "code": code,
                        "imports": imports,
                    }
                )
            elif isinstance(node, ast.Assign) and is_constant_assign(node):
                names = []
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.append(t.id)
                    elif isinstance(t, ast.Tuple):
                        for e in t.elts:
                            if isinstance(e, ast.Name):
                                names.append(e.id)
                name = names[0] if names else "CONST"
                code = node_to_code(node)
                h = sha256_text(code)
                results.append(
                    {
                        "kind": "const",
                        "name": name,
                        "hash": h,
                        "code": code,
                        "imports": imports,
                    }
                )
        except Exception as exc:
            logger.exception("error extracting node in {}: {}", origin, exc)
    return path_str, results


def partition_by_hash(
    extracted_map: dict[str, list[tuple[SourceFile, dict]]],
) -> dict[str, list[tuple[SourceFile, dict]]]:
    return extracted_map


def ensure_utils_dir() -> None:
    UTILS_DIR.mkdir(exist_ok=True)


def append_unique_to_file(target: Path, items: list[dict], seen_hashes: set) -> None:
    if not items:
        return
    lines = []
    if target.exists():
        base = target.read_text(encoding="utf-8")
    else:
        base = ""
    for it in items:
        if it["hash"] in seen_hashes:
            continue
        lines.append(it["code"])
        seen_hashes.add(it["hash"])
    if not lines:
        return
    new_text = base.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    target.write_text(new_text, encoding="utf-8")


def safe_write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def remove_nodes_from_source(original_src: str, nodes_to_remove: list[str]) -> str:
    out = original_src
    for snippet in nodes_to_remove:
        idx = out.find(snippet)
        if idx != -1:
            start = idx
            end = idx + len(snippet)
            while start > 0 and out[start - 1] in "\n\r\t ":
                start -= 1
                if out[start] == "\n":
                    break
            while end < len(out) and out[end] in "\n\r\t ":
                end += 1
                if out[end - 1] == "\n":
                    break
            out = out[:start] + out[end:]
        else:
            first_line = snippet.splitlines()[0]
            idx = out.find(first_line)
            if idx != -1:
                rest = out[idx:]
                nn = rest.find("\n\n")
                if nn != -1:
                    out = out[:idx] + out[idx + nn + 2 :]
                else:
                    out = out[:idx]
            else:
                logger.debug("could not find snippet to remove: {}", first_line[:60])
    return out


def add_imports_to_source(original_src: str, import_lines: list[str]) -> str:
    try:
        tree = ast.parse(original_src)
    except Exception:
        return "\n".join(import_lines) + "\n\n" + original_src
    insert_at = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        doc = tree.body[0]
        if hasattr(doc, "end_lineno"):
            insert_at = doc.end_lineno
        else:
            insert_at = 1
    lines = original_src.splitlines()
    new_lines = lines[:insert_at] + import_lines + [""] + lines[insert_at:]
    return "\n".join(new_lines) + "\n"


def validate_python_source(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except SyntaxError as e:
        logger.error("validation failed: {}:{}", e.lineno, e.msg)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deduplicate top-level funcs/classes/constants into utils/*"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="move duplicated objects (default off)",
    )
    group.add_argument(
        "-c",
        "--copy",
        action="store_true",
        help="copy duplicated objects (default off)",
    )
    parser.add_argument(
        "--min-occurs",
        type=int,
        default=2,
        help="minimum occurrences to consider duplicate (default 2)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, cpu_count() - 1),
        help="multiprocessing workers",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")
    if not (args.move or args.copy):
        parser.error("one of --move or --copy required")
    root = Path.cwd()
    print("scanning for Python sources under {}", root)
    sources = list(iter_python_sources(root))
    print("found {} candidate sources", len(sources))
    tasks = [(str(s.path), str(s.relpath), s.text, s.origin) for s in sources]
    extracted_map: dict[str, list[tuple[SourceFile, dict]]] = {}
    with Pool(processes=args.jobs) as pool:
        for path_str, items in pool.imap_unordered(extract_defs_from_source, tasks):
            if not items:
                continue
            srcfile = next((s for s in sources if str(s.path) == path_str), None)
            if not srcfile:
                srcfile = next(
                    (s for s in sources if s.origin.startswith(path_str)), None
                )
            for it in items:
                h = it["hash"]
                extracted_map.setdefault(h, []).append((srcfile, it))
    dups = {h: lst for h, lst in extracted_map.items() if len(lst) >= args.min_occurs}
    print(
        "found {} duplicated code blocks (occurring >= {})", len(dups), args.min_occurs
    )
    ensure_utils_dir()
    funcs_to_write = []
    classes_to_write = []
    consts_to_write = []
    modifications: dict[Path, dict[str, list]] = {}
    for h, instances in dups.items():
        srcfile, it = instances[0]
        kind = it["kind"]
        name = it["name"]
        code = it["code"]
        imports = it["imports"]
        for sf, _info in instances:
            if args.copy:
                pass
            else:
                sf.relpath if sf else Path("<unknown>")
                disk_path = sf.path if sf else None
                if disk_path and disk_path.exists() and disk_path.suffixes:
                    sf.path if sf.path.exists() else None
                d = modifications.setdefault(
                    sf.path,
                    {
                        "remove_snippets": [],
                        "add_imports": set(),
                        "preserve_imports": [],
                    },
                )
                d["remove_snippets"].append(code)
                if kind == "func":
                    mod = "utils.funcs"
                elif kind == "class":
                    mod = "utils.classes"
                else:
                    mod = "utils.const"
                d["add_imports"].add(f"from {mod} import {name}")
                for im in imports:
                    try:
                        s = ast.unparse(im)
                    except Exception:
                        s = node_to_code(im).strip()
                    d["preserve_imports"].append(s)
        if kind == "func":
            funcs_to_write.append({"hash": h, "code": code})
        elif kind == "class":
            classes_to_write.append({"hash": h, "code": code})
        elif kind == "const":
            consts_to_write.append({"hash": h, "code": code})
    seen_func_hashes = set()
    seen_class_hashes = set()
    seen_const_hashes = set()
    if FUNC_FILE.exists():
        try:
            existing = FUNC_FILE.read_text(encoding="utf-8")
            seen_func_hashes = {
                sha256_text(block) for block in existing.split("\n\n") if block.strip()
            }
        except Exception:
            seen_func_hashes = set()
    if CLASS_FILE.exists():
        try:
            existing = CLASS_FILE.read_text(encoding="utf-8")
            seen_class_hashes = {
                sha256_text(block) for block in existing.split("\n\n") if block.strip()
            }
        except Exception:
            seen_class_hashes = set()
    if CONST_FILE.exists():
        try:
            existing = CONST_FILE.read_text(encoding="utf-8")
            seen_const_hashes = {
                sha256_text(block) for block in existing.split("\n\n") if block.strip()
            }
        except Exception:
            seen_const_hashes = set()
    append_unique_to_file(FUNC_FILE, funcs_to_write, seen_func_hashes)
    append_unique_to_file(CLASS_FILE, classes_to_write, seen_class_hashes)
    append_unique_to_file(CONST_FILE, consts_to_write, seen_const_hashes)
    print("written utils files under {}", UTILS_DIR)
    if args.move:
        print(
            "applying move modifications to original files ({} targets)",
            len(modifications),
        )
        for src_path, mod in modifications.items():
            try:
                if not src_path or not Path(src_path).exists():
                    logger.warning("original file {} not on disk (skipping)", src_path)
                    continue
                p = Path(src_path)
                orig_text = p.read_text(encoding="utf-8")
                new_text = remove_nodes_from_source(orig_text, mod["remove_snippets"])
                import_lines = sorted(mod["add_imports"])
                new_text = add_imports_to_source(new_text, import_lines)
                if not validate_python_source(new_text):
                    logger.error(
                        "after modifications, file {} has syntax errors; skipping write",
                        p,
                    )
                    continue
                with tempfile.NamedTemporaryFile(
                    "w", delete=False, encoding="utf-8"
                ) as tf:
                    tf.write(new_text)
                    tmpname = tf.name
                Path(tmpname).replace(p)
                print("updated {}", p)
            except Exception as exc:
                logger.exception("failed to modify {}: {}", src_path, exc)
    print("done")


if __name__ == "__main__":
    raise SystemExit(main())
