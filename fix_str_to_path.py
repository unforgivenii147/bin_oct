#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re


def add_path_statement(path: str) -> bool:
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    modified_lines = []
    in_function = False
    function_indent = None
    added = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*def process_file\(", line):
            in_function = True
            modified_lines.append(line)
            continue
        if in_function and not added:
            stripped = line.strip()
            if stripped and (stripped.startswith(('"""', "'''"))):
                modified_lines.append(line)
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    modified_lines.append(line)
                    continue
                else:
                    continue
            if function_indent is None:
                for j in range(i - 1, -1, -1):
                    if re.match(r"^\s*def process_file\(", modified_lines[j]):
                        func_line = modified_lines[j]
                        function_indent = (
                            re.match(r"^(\s*)", func_line).group(1) + "    "
                        )
                        break
            current_indent = re.match(r"^(\s*)", line).group(1)
            if current_indent.startswith(function_indent.rstrip()) and stripped:
                modified_lines.append(f"{function_indent}path = Path(path)\n")
                print(f"Added 'path = Path(path)' to {path}")
                added = True
                in_function = False
        modified_lines.append(line)
    if added:
        with open(path, "w", encoding="utf-8") as file:
            file.writelines(modified_lines)
        return True
    else:
        print(
            f"Skipping {path}: No process_file function found or already has the line"
        )
        return False


def add_path_statement_simple(path: str) -> bool:
    with open(path, encoding="utf-8") as file:
        content = file.read()
    if "path=Path(path)" in content or "path = Path(path)" in content:
        print(f"Skipping {path}: path=Path(path) already exists")
        return False
    pattern = "(def process_file\\([^:]*:)\\s*\\n\\s*(?:\"\"\"[\\s\\S]*?\"\"\"|\\'\\'\\'[\\s\\S]*?\\'\\'\\')\\s*\\n?\\s*"

    def replacement(match):
        full_match = match.group(0)
        func_line = match.group(1)
        indent = re.match(r"^(\s*)", func_line).group(1) + "    "
        return (
            f"{func_line}\n{indent}path = Path(path)\n" + full_match[len(func_line) :]
        )

    new_content = re.sub(pattern, replacement, content, count=1)
    if new_content == content:
        pattern = "(def process_file\\([^:]*:)\\s*\\n\\s*"

        def replacement2(match) -> str:
            indent = re.match(r"^(\s*)", match.group(1)).group(1) + "    "
            return f"{match.group(1)}\n{indent}path = Path(path)\n"

        new_content = re.sub(pattern, replacement2, content, count=1)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as file:
            file.write(new_content)
        print(f"Added 'path = Path(path)' to {path}")
        return True
    return False


def process_directory() -> None:
    cwd = os.getcwd()
    python_files = [
        f for f in os.listdir(cwd) if f.endswith(".py") and os.path.isfile(f)
    ]
    if not python_files:
        print("No Python files found in current directory")
        return
    print(f"Found {len(python_files)} Python file(s) to process")
    print("-" * 40)
    modified_count = 0
    for file_name in python_files:
        path = os.path.join(cwd, file_name)
        if add_path_statement_simple(path) or add_path_statement(path):
            modified_count += 1
    print("-" * 40)
    print(f"Modified {modified_count} file(s)")


if __name__ == "__main__":
    process_directory()
