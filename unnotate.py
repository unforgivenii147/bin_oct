#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

try:
    from tree_sitter import Parser

    try:
        from tree_sitter_languages import get_language

        PY_LANGUAGE = get_language("python")
    except Exception as exc:
        raise RuntimeError(
            "Failed to load prebuilt Python grammar from tree_sitter_languages. "
            "Install 'tree_sitter_languages' (pip install tree_sitter_languages)."
        ) from exc
except Exception as exc:
    raise RuntimeError(
        "tree-sitter is required. Install with: pip install tree_sitter tree_sitter_languages"
    ) from exc
TYPE_COMMENT_RE = re.compile(r"\s*#\s*type\s*:\s*([^\n]*)$", flags=re.IGNORECASE)


@dataclass
class Result:
    path: Path
    changed: bool
    warnings: list[str]
    error: str | None


def _prev_nonspace(buf: bytes, i: int) -> int:
    j = i - 1
    while j >= 0 and buf[j] in b" \t\r":
        j -= 1
    return j


def _next_nonspace(buf: bytes, i: int) -> int:
    n = len(buf)
    j = i
    while j < n and buf[j] in b" \t\r":
        j += 1
    return min(n, j)


def _collect_annotation_nodes(root) -> list:
    stack = [root]
    ann_nodes = []
    while stack:
        node = stack.pop()
        if node.type == "annotation":
            ann_nodes.append(node)
        for c in node.children:
            stack.append(c)
    return ann_nodes


def _remove_ranges_from_bytes(src: bytes, ranges: list[tuple[int, int]]) -> bytes:
    if not ranges:
        return src
    ranges_sorted = sorted(ranges, key=lambda r: r[0])
    merged = []
    cur_s, cur_e = ranges_sorted[0]
    for s, e in ranges_sorted[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    out = bytearray(src)
    for s, e in reversed(merged):
        del out[s:e]
    return bytes(out)


def process_file(path_str: str) -> Result:
    p = Path(path_str)
    warnings: list[str] = []
    if not p.exists():
        return Result(p, False, warnings, f"not found")
    try:
        src_bytes = p.read_bytes()
    except Exception as e:
        return Result(p, False, warnings, f"read error: {e}")
    parser = Parser()
    parser.set_language(PY_LANGUAGE)
    try:
        tree = parser.parse(src_bytes)
    except Exception as e:
        return Result(p, False, warnings, f"parse error: {e}")
    root = tree.root_node
    ann_nodes = _collect_annotation_nodes(root)
    remove_ranges: list[tuple[int, int]] = []
    for node in ann_nodes:
        s = node.start_byte
        e = node.end_byte
        prev_i = _prev_nonspace(src_bytes, s)
        removed_prefix_start = s
        if prev_i >= 1 and src_bytes[prev_i - 1 : prev_i + 1] == b"->":
            removed_prefix_start = prev_i - 1
        elif prev_i >= 0 and src_bytes[prev_i] == ord(":"):
            removed_prefix_start = prev_i
        else:
            removed_prefix_start = s
        next_i = _next_nonspace(src_bytes, e)
        next_char = src_bytes[next_i : next_i + 1] if next_i < len(src_bytes) else b""
        safe_next = next_char in (b"=", b",", b")", b":")
        if src_bytes[removed_prefix_start : removed_prefix_start + 2] == b"->":
            safe = True
        else:
            safe = safe_next
        if not safe:
            line_start = src_bytes.rfind(b"\n", 0, s) + 1
            line_end = src_bytes.find(b"\n", e)
            if line_end == -1:
                line_end = len(src_bytes)
            snippet = src_bytes[line_start:line_end].decode(errors="replace").strip()
            warnings.append(
                f'skipped standalone annotation at {p}:{node.start_point[0] + 1}: "{snippet}"'
            )
            continue
        remove_ranges.append((removed_prefix_start, e))
    type_comment_ranges: list[tuple[int, int]] = []
    for m in TYPE_COMMENT_RE.finditer(src_bytes.decode(errors="ignore")):
        pass
    lines = src_bytes.splitlines(keepends=True)
    offset = 0
    for ln in lines:
        try:
            text = ln.decode()
        except Exception:
            offset += len(ln)
            continue
        m = TYPE_COMMENT_RE.search(text)
        if m:
            byte_start = offset + len(text[: m.start(0)].encode())
            byte_end = offset + len(text[: m.end(0)].encode())
            type_comment_ranges.append((byte_start, byte_end))
        offset += len(ln)
    all_remove = remove_ranges + type_comment_ranges
    if not all_remove:
        return Result(p, False, warnings, None)
    new_bytes = _remove_ranges_from_bytes(src_bytes, all_remove)
    if new_bytes == src_bytes:
        return Result(p, False, warnings, None)
    try:
        parent = p.parent
        fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".tmp_removeann_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(new_bytes)
        st = p.stat()
        os.chmod(tmp_path, stat.S_IMODE(st.st_mode))
        os.replace(tmp_path, str(p))
        return Result(p, True, warnings, None)
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return Result(p, False, warnings, f"write error: {e}")


def gather_py_files(paths: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    provided = list(paths)
    if not provided:
        provided = ["."]
    for p in provided:
        path = Path(p)
        if path.is_file():
            if path.suffix == ".py":
                out.append(path.resolve())
        elif path.is_dir():
            for f in path.rglob("*.py"):
                if f.is_file():
                    out.append(f.resolve())
        else:
            for f in Path(".").glob(p):
                if f.is_file() and f.suffix == ".py":
                    out.append(f.resolve())
    unique = sorted({p for p in out})
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove Python type annotations from .py files (in-place)."
    )
    parser.add_argument(
        "paths", nargs="*", help="Files or directories to process (default: .)"
    )
    parser.add_argument(
        "--jobs",
        action="store_true",
        help="(ignored) pool size is fixed to 8 as required; flag kept for compatibility",
    )
    args = parser.parse_args(argv)
    files = gather_py_files(args.paths)
    if not files:
        print("No .py files found.", file=sys.stderr)
        return 1
    pool_size = 8
    pool = mp.Pool(processes=pool_size)
    results = []
    pending = []

    def _collect_result(res: Result):
        results.append(res)

    for f in files:
        a = pool.apply_async(process_file, args=(str(f),), callback=_collect_result)
        pending.append(a)
    for a in pending:
        try:
            a.wait()
        except KeyboardInterrupt:
            print("Interrupted; terminating workers...", file=sys.stderr)
            pool.terminate()
            pool.join()
            return 130
    pool.close()
    pool.join()
    changed = [r for r in results if r.changed and r.error is None]
    failed = [r for r in results if r.error]
    skipped = [r for r in results if (not r.changed) and (not r.error)]
    warnings = [w for r in results for w in r.warnings]
    for r in changed:
        print(f"updated: {r.path}")
    for r in skipped:
        print(f"no-change: {r.path}")
    for r in failed:
        print(f"error: {r.path} -> {r.error}")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print("  -", w)
    print(
        f"\nSummary: processed={len(results)} updated={len(changed)} no-change={len(skipped)} errors={len(failed)} warnings={len(warnings)}"
    )
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
