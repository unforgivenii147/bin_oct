#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import io
import multiprocessing
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple

try:
    import astor
except Exception:
    print(
        "This script requires the 'astor' package. Install with: pip install astor",
        file=sys.stderr,
    )
    sys.exit(2)


class RemovalStats(NamedTuple):
    docstrings_removed: int
    comments_removed: int


class DocstringStripper(ast.NodeTransformer):
    def __init__(self):
        self.docstrings_removed = 0

    def _strip_docstring(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if not body:
            return node
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body.pop(0)
            self.docstrings_removed += 1
            if not body:
                body.append(ast.Pass())
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)


def extract_prefix_comments_and_shebang(source: str) -> tuple[str, str]:
    lines = source.splitlines(keepends=True)
    prefix_lines: list[str] = []
    i = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and line.startswith("#!"):
            prefix_lines.append(line)
            continue
        if stripped == "":
            if prefix_lines:
                prefix_lines.append(line)
            continue
        if stripped.startswith("#"):
            low = stripped.lower()
            if any(x in low for x in ("coding", "encoding", "type:", "fmt:")):
                prefix_lines.append(line)
                continue
            break
        break
    prefix = "".join(prefix_lines)
    remainder = "".join(lines[i:]) if i < len(lines) else ""
    return (prefix, remainder)


def collect_and_strip_comments(source: str) -> tuple[str, dict[int, list[str]], int]:
    lines = source.splitlines(keepends=True)
    preserved_comments: dict[int, list[str]] = {}
    comments_to_remove: dict[int, set] = {}
    comments_removed = 0
    sio = io.StringIO(source)
    try:
        for tok in tokenize.generate_tokens(sio.readline):
            if tok.type == tokenize.COMMENT:
                tok_string = tok.string
                low = tok_string.lower()
                row = tok.start[0]
                col = tok.start[1]
                if any(x in low for x in ("type:", "fmt:", "noqa")):
                    preserved_comments.setdefault(row, []).append(tok_string)
                else:
                    line_before_comment = lines[row - 1][:col].rstrip()
                    if not line_before_comment:
                        comments_to_remove.setdefault(row, set()).add(tok_string)
                        comments_removed += 1
    except tokenize.TokenError:
        pass
    return (preserved_comments, comments_removed)


def process_file(path: Path) -> tuple[str, bool, str | None, RemovalStats]:
    try:
        with tokenize.open(path) as f:
            original = f.read()
            encoding = f.encoding
    except Exception as exc:
        return (str(path), False, f"read-error: {exc}", RemovalStats(0, 0))
    if not original.strip():
        return (str(path), False, None, RemovalStats(0, 0))
    prefix, _code_part = extract_prefix_comments_and_shebang(original)
    preserved_inline_comments, comments_removed = collect_and_strip_comments(original)
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return (str(path), False, f"syntax-error-original: {exc}", RemovalStats(0, 0))
    stripper = DocstringStripper()
    new_tree = stripper.visit(tree)
    ast.fix_missing_locations(new_tree)
    try:
        new_source = astor.to_source(new_tree)
    except Exception as exc:
        return (str(path), False, f"unparse-failed: {exc}", RemovalStats(0, 0))
    combined = prefix + new_source
    combined = reattach_inline_comments(combined, preserved_inline_comments)
    combined = combined.rstrip("\n") + "\n"
    try:
        ast.parse(combined)
    except SyntaxError as exc:
        return (
            str(path),
            False,
            f"syntax-error-transformed: {exc}",
            RemovalStats(0, 0),
        )
    if combined == original:
        return (str(path), False, None, RemovalStats(0, 0))
    try:
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(combined)
    except Exception as exc:
        return (str(path), False, f"write-error: {exc}", RemovalStats(0, 0))
    stats = RemovalStats(stripper.docstrings_removed, comments_removed)
    return (str(path), True, None, stats)


def reattach_inline_comments(
    new_source: str, preserved_comments: dict[int, list[str]]
) -> str:
    if not preserved_comments:
        return new_source
    new_lines = new_source.splitlines()
    max_line = len(new_lines)
    attached = set()
    for orig_line_no in sorted(preserved_comments.keys()):
        target_idx = orig_line_no - 1
        if 0 <= target_idx < max_line:
            for comment in preserved_comments[orig_line_no]:
                line = new_lines[target_idx]
                if comment not in line:
                    if line.rstrip():
                        new_lines[target_idx] = line + "  " + comment
                    else:
                        new_lines[target_idx] = comment
                attached.add((orig_line_no, comment))
    for orig_line_no in sorted(preserved_comments.keys()):
        for comment in preserved_comments[orig_line_no]:
            if (orig_line_no, comment) not in attached:
                new_lines.append(comment)
    result = "\n".join(new_lines)
    if new_source.endswith("\n") and (not result.endswith("\n")):
        result += "\n"
    return result


def should_skip_path(p: Path) -> bool:
    parts = {part.lower() for part in p.parts}
    skip_indicators = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".tox",
        "build",
        "dist",
    }
    return bool(parts & skip_indicators)


def collect_py_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix == ".py" and (not path.is_symlink()):
                files.append(path)
        elif path.is_dir():
            for p in path.rglob("*.py"):
                if should_skip_path(p) or p.is_symlink():
                    continue
                files.append(p)
    return list(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strip docstrings and comments from Python files", prog="strip-py"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )
    args = parser.parse_args()
    if not args.paths:
        paths = [Path.cwd()]
    else:
        paths = args.paths
    files = collect_py_files(paths)
    if not files:
        print("No .py files found.")
        return 0
    print(f"Processing {len(files)} file(s)...\n")
    changed: list[tuple[str, RemovalStats]] = []
    errors: list[tuple[str, str]] = []
    workers = max(1, min(32, multiprocessing.cpu_count()))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_file, p): p for p in files}
        for fut in concurrent.futures.as_completed(futures):
            try:
                path_str, did_change, err, stats = fut.result()
                if err:
                    errors.append((path_str, err))
                elif did_change:
                    changed.append((path_str, stats))
            except Exception as exc:
                p = futures[fut]
                errors.append((str(p), f"worker-exception: {exc}"))
    if changed:
        total_docstrings = 0
        total_comments = 0
        print("Modified files:")
        for p in sorted(changed, key=lambda x: x[0]):
            path_str, stats = p
            total_docstrings += stats.docstrings_removed
            total_comments += stats.comments_removed
            print(
                f"  {Path(path_str).name}: {stats.docstrings_removed} docstring(s), {stats.comments_removed} comment(s)"
            )
        print(
            f"\nTotals: {total_docstrings} docstring(s), {total_comments} comment(s) removed\n"
        )
    if errors:
        print("Errors:", file=sys.stderr)
        for p, e in sorted(errors):
            print(f"  {p}: {e}", file=sys.stderr)
        return 2
    if not changed:
        print("No changes made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
