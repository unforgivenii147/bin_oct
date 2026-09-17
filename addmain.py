#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def has_main_guard(tree: ast.AST) -> bool:
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.If):
            test = node.test
            if not isinstance(test, ast.Compare):
                continue
            if not (len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)):
                continue
            left = test.left
            if not (isinstance(left, ast.Name) and left.id == "__name__"):
                continue
            if len(test.comparators) != 1:
                continue
            comp = test.comparators[0]
            if isinstance(comp, ast.Constant) and comp.value == "__main__":
                return True
    return False


def is_docstring_expr(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    return bool(
        isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    )


def should_wrap_node(node: ast.stmt) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return False
    if is_docstring_expr(node):
        return False
    if isinstance(node, ast.If):
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
        ):
            left = test.left
            if (
                isinstance(left, ast.Name)
                and left.id == "__name__"
                and len(test.comparators) == 1
            ):
                comp = test.comparators[0]
                if isinstance(comp, ast.Constant) and comp.value == "__main__":
                    return False
    return True


def indent_block(block: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    lines = block.splitlines(True)
    out = []
    for ln in lines:
        if ln.strip() == "":
            out.append(ln)
        else:
            out.append(prefix + ln)
    return "".join(out)


def rewrite_file(path: Path) -> tuple[bool, str]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return False, f"SKIP parse error: {e}"
    if has_main_guard(tree):
        return False, "SKIP already has main guard"
    nodes = list(tree.body)
    wrap_nodes = [n for n in nodes if should_wrap_node(n)]
    if not wrap_nodes:
        return False, "SKIP nothing to wrap"
    lines = src.splitlines(True)

    def segment(start: int, end: int) -> str:
        return "".join(lines[start - 1 : end])

    main_parts: list[str] = []
    keep_segments: list[tuple[int, int]] = []
    for n in nodes:
        start = getattr(n, "lineno", None)
        end = getattr(n, "end_lineno", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return False, "SKIP missing lineno/end_lineno (AST limitation)"
        if should_wrap_node(n):
            main_parts.append(segment(start, end).rstrip() + "\n")
        else:
            keep_segments.append((start, end))
    keep_segments.sort()
    new_parts: list[str] = []
    cursor = 1
    for start, end in keep_segments:
        if start > cursor:
            new_parts.append("".join(lines[cursor - 1 : start - 1]))
        new_parts.append("".join(lines[start - 1 : end]))
        cursor = end + 1
    if cursor <= len(lines):
        new_parts.append("".join(lines[cursor - 1 :]))
    main_body = "".join(main_parts).rstrip("\n")
    main_fn = ""
    main_fn += "\n\n"
    main_fn += "def main():\n"
    if main_body.strip() == "":
        main_fn += "    pass\n"
    else:
        main_fn += indent_block(main_body + "\n", 4).rstrip("\n") + "\n"
    main_fn += "\n\n"
    main_fn += 'if __name__ == "__main__":\n'
    main_fn += "    raise SystemExit(main())\n"
    new_src = "".join(new_parts).rstrip() + main_fn
    path.write_text(new_src, encoding="utf-8")
    return True, "OK autofixed"


def iter_py_files(inputs: list[str]) -> list[Path]:
    if not inputs:
        roots = [Path(".")]
    else:
        roots = [Path(p) for p in inputs]
    out: list[Path] = []
    for r in roots:
        if r.is_dir():
            out.extend(sorted(x for x in r.rglob("*.py") if x.is_file()))
        else:
            if r.suffix == ".py" and r.is_file():
                out.append(r)
    return sorted(set(out))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to scan (default: current dir recursively)",
    )
    p.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Wrap top-level code in main() and add main guard",
    )
    args = p.parse_args(argv)
    files = iter_py_files(args.paths)
    any_changed = False
    any_missing = False
    for f in files:
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            print(f"{f}: SKIP parse error", file=sys.stderr)
            continue
        if has_main_guard(tree):
            continue
        any_missing = True
        if args.autofix:
            changed, msg = rewrite_file(f)
            if changed:
                any_changed = True
            print(f"{f}: {msg}")
        else:
            print(f"{f}: MISSING main guard")
    if args.autofix:
        return 0 if any_changed else (0 if not any_missing else 2)
    return 0 if not any_missing else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
