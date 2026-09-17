#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import multiprocessing as mp
import re
import sys
from pathlib import Path


class Colors:
    GREEN = "\033[92m"
    WHITE = "\033[97m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def should_skip_dir(path: Path) -> bool:
    return path.name in {".git", "__pycache__"}


def get_py_files(root: Path = Path(".")) -> list[Path]:
    py_files = []

    def walk(directory: Path):
        try:
            for item in directory.iterdir():
                if item.is_dir():
                    if not should_skip_dir(item):
                        walk(item)
                elif item.is_file() and item.suffix == ".py":
                    py_files.append(item)
        except (PermissionError, OSError):
            pass

    walk(root)
    return sorted(py_files)


def is_shebang(line: str, line_num: int) -> bool:
    return line_num == 0 and line.strip().startswith("#!")


def is_type_or_fmt_directive(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"#\s*(type|fmt):", stripped))


def is_module_docstring(tree: ast.AST, node: ast.Expr) -> bool:
    if not isinstance(node, ast.Expr):
        return False
    if not isinstance(node.value, ast.Constant):
        return False
    if not isinstance(node.value.value, str):
        return False
    return bool(tree.body and tree.body[0] is node)


def parse_file_for_docstrings(path: Path) -> list[tuple[int, str, bool]]:
    docstring_lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return docstring_lines
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                if is_module_docstring(tree, node):
                    continue
                if hasattr(node, "lineno"):
                    docstring_lines.append((node.lineno - 1, None, True))
        return docstring_lines
    except Exception:
        return docstring_lines


def find_comments_and_docstrings(path: Path) -> list[tuple[int, str, bool]]:
    findings = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        docstring_line_nums = set()
        docstring_nodes = parse_file_for_docstrings(path)
        for line_num, _, _ in docstring_nodes:
            docstring_line_nums.add(line_num)
        for idx, line in enumerate(lines):
            if "#" in line:
                if is_shebang(line, idx):
                    continue
                if is_type_or_fmt_directive(line):
                    continue
                comment_pos = line.find("#")
                if comment_pos != -1:
                    before_hash = line[:comment_pos]
                    if (
                        before_hash.count('"') % 2 == 0
                        and before_hash.count("'") % 2 == 0
                    ):
                        findings.append((idx, line.rstrip(), False))
    except Exception:
        pass
    return findings


def process_file(path: Path) -> tuple[Path, list[tuple[int, str, bool]]]:
    findings = find_comments_and_docstrings(path)
    return (path, findings)


def print_finding(
    path: Path,
    line_num: int,
    line_content: str,
    all_lines: list[str],
    is_comment: bool = True,
):
    path = Path(path).resolve()
    finding_type = "Comment" if is_comment else "Docstring"
    print(f"\n{path.relative_to(Path.cwd().resolve())}:{line_num + 1}")
    start = max(0, line_num - 2)
    end = min(len(all_lines), line_num + 3)
    for i in range(start, end):
        if i == line_num:
            print(f"{Colors.GREEN}{i + 1:4d} | {all_lines[i].rstrip()}{Colors.RESET}")
        else:
            print(f"{Colors.WHITE}{i + 1:4d} | {all_lines[i].rstrip()}{Colors.RESET}")


def remove_finding(path: Path, line_num: int, all_lines: list[str]) -> list[str]:
    if line_num < len(all_lines):
        all_lines.pop(line_num)
    return all_lines


def main():
    parser = argparse.ArgumentParser(
        description="Find comments and docstrings in Python files."
    )
    parser.add_argument(
        "-a",
        "--auto-remove",
        action="store_true",
        help="Automatically remove found comments and docstrings.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of worker processes (default: 4).",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory).",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory)
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory.", file=sys.stderr)
        sys.exit(1)
    py_files = get_py_files(root_dir)
    if not py_files:
        print("No Python files found.")
        return
    print(f"Scanning {len(py_files)} Python files with {args.workers} workers...\n")
    with mp.Pool(args.workers) as pool:
        results = pool.map(process_file, py_files)
    all_findings = {}
    total_findings = 0
    for path, findings in results:
        if findings:
            all_findings[path] = findings
            total_findings += len(findings)
    if not all_findings:
        print("No comments or docstrings found.")
        return
    print(f"Found {total_findings} comments/docstrings:\n")
    print("=" * 40)
    for path in sorted(all_findings.keys()):
        findings = all_findings[path]
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                file_lines = f.readlines()
            sorted_findings = sorted(findings, key=lambda x: x[0], reverse=True)
            for line_num, line_content, is_docstring in sorted_findings:
                print_finding(
                    path, line_num, line_content, file_lines, not is_docstring
                )
                if args.auto_remove:
                    file_lines = remove_finding(path, line_num, file_lines)
            if args.auto_remove:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(file_lines)
                print(f"{Colors.YELLOW}[REMOVED]{Colors.RESET}", end=" ")
        except Exception as e:
            print(f"Error processing {path}: {e}", file=sys.stderr)
    print("\n" + "=" * 40)
    if args.auto_remove:
        print(
            f"{Colors.YELLOW}Removed {total_findings} comments/docstrings.{Colors.RESET}"
        )
    else:
        print(f"Total findings: {total_findings}")
        print("Use -a/--auto-remove flag to remove them.")


if __name__ == "__main__":
    raise SystemExit(main())
