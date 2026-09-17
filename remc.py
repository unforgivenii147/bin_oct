#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import re
import sys
from ast import Module
from collections import deque
from pathlib import Path

from dh import cprint, fsz, get_files, gsz


def rm_doc(content: str) -> tuple[str, int]:
    removed_count = 0
    lines = content.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if DOC_TH1 in line or DOC_TH2 in line:
            delimiter = DOC_TH1 if DOC_TH1 in line else DOC_TH2
            count = line.count(delimiter)
            if count >= 2:
                first = line.find(delimiter)
                second = line.find(delimiter, first + 3)
                before = line[:first].rstrip()
                if before.endswith(":") or before.strip() == "":
                    result_lines.append(line[:first] + line[second + 3 :])
                    removed_count += 1
                    i += 1
                    continue
            before = line[: line.find(delimiter)].rstrip()
            if before.endswith(":") or before.strip() == "" or "=" not in before:
                removed_count += 1
                if before:
                    result_lines.append(before)
                j = i + 1
                while j < len(lines):
                    if delimiter in lines[j]:
                        after = lines[j][lines[j].find(delimiter) + 3 :].strip()
                        if after:
                            result_lines.append(after)
                        i = j + 1
                        break
                    j += 1
                else:
                    i = j
            else:
                result_lines.append(line)
                i += 1
        else:
            result_lines.append(line)
            i += 1
    return ("\n".join(result_lines), removed_count)


def rm_ast(content: str) -> tuple[str, int]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return rm_doc(content)
    lines = content.split("\n")
    ranges = find_docstring_ranges(tree)
    for start, end in sorted(ranges, reverse=True):
        del lines[start - 1 : end]
    return ("\n".join(lines), len(ranges))


def find_docstring_ranges(node: Module) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for child in ast.walk(node):
        if (
            isinstance(
                child, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and child.body
            and isinstance(child.body[0], ast.Expr)
        ):
            value = child.body[0].value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and child.body[0].lineno
                and child.body[0].end_lineno
            ):
                ranges.append((child.body[0].lineno, child.body[0].end_lineno))
    return ranges


def remove_blank_lines(content: str) -> str:
    content = re.sub(r"\n\n+", "\n", content)
    return "\n".join(line.rstrip() for line in content.split("\n"))


def process_file(path: Path) -> None:
    Path(path)
    try:
        original = path.read_text(encoding="utf-8")
        try:
            modified, removed = rm_ast(original)
        except:
            modified, removed = rm_doc(original)
        modified = remove_blank_lines(modified)
        if removed:
            print(f"✓ {path.name} : ", end="")
            cprint(f"{removed}", "cyan")
            try:
                tree = ast.parse(modified)
                path.write_text(modified, encoding="utf-8")
                del tree
                return
            except:
                cprint(f"{path.name} ast parse error", "cyan")
                return
    except Exception as exc:
        print(f"✗ Error processing {path}: {exc}")
        return


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    with Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    diff_size = before - gsz(cwd)
    print(f"space saved : {fsz(diff_size)}")


if __name__ == "__main__":
    raise SystemExit(main())
DOC_TH1 = '"""'
DOC_TH2 = "'''"
