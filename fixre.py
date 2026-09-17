#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import shutil
import sys
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path

RE_FUNCTIONS = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "split",
    "findall",
    "finditer",
    "sub",
    "subn",
}
REGEX_INDICATORS = {
    "\\d",
    "\\w",
    "\\s",
    "\\S",
    "\\W",
    "\\D",
    "[",
    "]",
    "(",
    ")",
    "|",
    "^",
    "$",
    "+",
    "*",
    "?",
    "{",
    "}",
    ".",
    "\\b",
    "\\B",
    "\\A",
    "\\Z",
    "\\z",
    "\\1",
    "\\2",
    "\\3",
    "\\4",
    "\\5",
    "\\6",
    "\\7",
    "\\8",
    "\\9",
}
STRING_ESCAPES = {"\\n", "\\t", "\\r", "\\f", "\\v", "\\\\", "\\'", '\\"', "\\a", "\\b"}


@dataclass
class StringInfo:
    value: str
    lineno: int
    col_offset: int
    end_col: int
    is_raw: bool = False
    is_fstring: bool = False
    quote_char: str = '"'


def needs_raw_string(string_content: str) -> bool:
    if not string_content:
        return False
    has_regex_pattern = any(
        indicator in string_content for indicator in REGEX_INDICATORS
    )
    escape_count = 0
    i = 0
    while i < len(string_content) - 1:
        if string_content[i] == "\\":
            if string_content[i + 1] in "\\abfnrtv\"'":
                escape_count += 1
                if escape_count >= 2 or (escape_count >= 1 and has_regex_pattern):
                    return True
            i += 1
        i += 1
    return False


def extract_and_convert_strings(content: str) -> str | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    conversions = []

    class RegexStringVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and (node.func.value.id == "re")
                and (node.func.attr in RE_FUNCTIONS)
                and node.args
            ):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    is_raw = False
                    is_fstring = False
                    if hasattr(arg, "lineno") and hasattr(arg, "col_offset"):
                        string_val = arg.value
                        if needs_raw_string(string_val):
                            conversions.append(
                                {
                                    "lineno": arg.lineno,
                                    "col_offset": arg.col_offset,
                                    "end_col": arg.end_col_offset,
                                    "value": string_val,
                                    "is_raw": is_raw,
                                    "is_fstring": is_fstring,
                                }
                            )
            self.generic_visit(node)

    visitor = RegexStringVisitor()
    visitor.visit(tree)
    if not conversions:
        return None
    lines = content.split("\n")
    converted = False
    conversions.sort(key=lambda x: (x["lineno"], -x["col_offset"]))
    for conv in conversions:
        line_idx = conv["lineno"] - 1
        if line_idx >= len(lines):
            continue
        line = lines[line_idx]
        col_start = conv["col_offset"]
        col_end = conv["end_col"]
        original_literal = line[col_start:col_end]
        if original_literal.startswith(('r"', "r'", 'r"""', "r'''")):
            continue
        if original_literal.startswith(('"""', "'''")):
            continue
        quote_char = original_literal[0] if original_literal else '"'
        if quote_char not in ['"', "'"]:
            continue
        escaped_value = conv["value"]
        new_literal = f"r{quote_char}{escaped_value}{quote_char}"
        new_line = line[:col_start] + new_literal + line[col_end:]
        lines[line_idx] = new_line
        converted = True
    if not converted:
        return None
    return "\n".join(lines)


def validate_python_file(content: str) -> bool:
    try:
        ast.parse(content)
        return True
    except SyntaxError:
        return False


def process_file(path: Path, create_backup: bool = True) -> tuple[Path, bool, str]:
    try:
        original_content = path.read_text(encoding="utf-8")
    except Exception as e:
        return (path, False, f"Failed to read: {e}")
    if "re." not in original_content:
        return (path, True, "No re calls found")
    converted_content = extract_and_convert_strings(original_content)
    if converted_content is None:
        return (path, True, "No changes needed")
    if not validate_python_file(converted_content):
        return (path, False, "Validation failed - syntax error after conversion")
    try:
        if create_backup:
            backup_path = path.with_suffix(path.suffix + ".backup")
            shutil.copy2(path, backup_path)
        path.write_text(converted_content, encoding="utf-8")
        return (path, True, "✓ Converted and saved")
    except Exception as e:
        return (path, False, f"Failed to write: {e}")


def collect_python_files(inputs: list[Path]) -> list[Path]:
    python_files = set()
    for input_path in inputs:
        if not input_path.exists():
            print(f"Warning: Path does not exist: {input_path}", file=sys.stderr)
            continue
        if input_path.is_file():
            if input_path.suffix == ".py":
                python_files.add(input_path)
        elif input_path.is_dir():
            skip_dirs = {".venv", "venv", "env", "__pycache__", ".git", "node_modules"}
            for py_file in input_path.rglob("*.py"):
                if any(part in skip_dirs for part in py_file.parts):
                    continue
                python_files.add(py_file)
    return sorted(python_files)


def parse_arguments():
    args = sys.argv[1:]
    if not args:
        return ([], True)
    create_backup = True
    if "--no-backup" in args:
        create_backup = False
        args.remove("--no-backup")
    num_workers = min(cpu_count(), 4)
    for i, arg in enumerate(args):
        if arg == "--workers" and i + 1 < len(args):
            try:
                num_workers = int(args[i + 1])
                args.pop(i)
                args.pop(i)
            except ValueError:
                pass
            break
    paths = [Path(arg).resolve() for arg in args] if args else [Path.cwd()]
    return (paths, create_backup, num_workers)


def main():
    paths, create_backup, num_workers = parse_arguments()
    python_files = collect_python_files(paths)
    if not python_files:
        print("No Python files found")
        return
    print(f"Found {len(python_files)} Python files")
    print(f"Processing with {num_workers} workers")
    print(f"Backup: {('Enabled' if create_backup else 'Disabled')}")
    print(f"Target re functions: {', '.join(sorted(RE_FUNCTIONS))}\n")
    results = []
    total = len(python_files)
    if num_workers > 1:
        with Pool(processes=num_workers) as pool:
            results = pool.starmap(
                process_file, [(f, create_backup) for f in python_files]
            )
    else:
        for i, path in enumerate(python_files, 1):
            if i % 100 == 0:
                print(f"Progress: {i}/{total}", flush=True)
            results.append(process_file(path, create_backup))
    successful = sum((1 for _, success, _ in results if success))
    changed = sum((1 for _, success, msg in results if success and "Converted" in msg))
    print("\n" + "=" * 40)
    for path, success, message in results:
        status = "✓" if success else "✗"
        try:
            rel_path = path.relative_to(Path.cwd())
        except ValueError:
            rel_path = path
        print(f"{status} {rel_path}: {message}")
    print("-" * 40)
    print("\nSummary:")
    print(f"  Total files: {len(python_files)}")
    print(f"  Processed successfully: {successful}")
    print(f"  Files converted: {changed}")
    if not create_backup:
        print("\n⚠️  Backup disabled. Use --no-backup with caution.")


if __name__ == "__main__":
    raise SystemExit(main())
