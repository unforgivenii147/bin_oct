#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from typing import dict, list, set, tuple

VULTURE_LINE_PATTERN = re.compile(
    r"^(.+?):(\d+):\s+(unused\s+(function|variable|class|attribute|method|import)\s+'([^']+)'|unreachable code after '(\w+)'|redundant if-condition|unreachable 'else' block|unused import '([^']+)'\s+\(\d+% confidence\))$"
)


def parse_vulture_output(lines: list[str]) -> dict[str, list[tuple[int, str, str]]]:
    results = defaultdict(list)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = VULTURE_LINE_PATTERN.match(line)
        if not match:
            continue
        path = match.group(1)
        line_num = int(match.group(2))
        full_message = match.group(3)
        issue_type = None
        name = None
        if match.group(4):
            issue_type = "unused_" + match.group(4)
            name = match.group(5)
        elif match.group(6):
            issue_type = "unreachable_after"
            name = match.group(6)
        elif "redundant if-condition" in full_message:
            issue_type = "redundant_if"
            name = ""
        elif "unreachable 'else' block" in full_message:
            issue_type = "unreachable_else"
            name = ""
        elif match.group(7):
            issue_type = "unused_import"
            name = match.group(7)
        else:
            issue_type = "other"
            name = ""
        results[path].append((line_num, issue_type, name))
    return dict(results)


def fix_file(path: str, issues: list[tuple[int, str, str]]) -> bool:
    if not os.path.exists(path):
        print(f"Warning: File not found: {path}")
        return False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return False
    original_lines = lines.copy()
    modified = False
    issues_sorted = sorted(issues, key=lambda x: x[0], reverse=True)
    lines_to_remove: set[int] = set()
    for line_num, issue_type, name in issues_sorted:
        idx = line_num - 1
        if idx < 0 or idx >= len(lines):
            continue
        if idx in lines_to_remove:
            continue
        line = lines[idx]
        try:
            if issue_type == "unused_variable":
                lines[idx] = _comment_out_variable(line, name)
                modified = True
            elif issue_type == "unused_function" or issue_type == "unused_method":
                func_lines = _get_function_lines(lines, idx)
                for i in range(func_lines[0], func_lines[1] + 1):
                    lines_to_remove.add(i)
                modified = True
            elif issue_type == "unused_class":
                class_lines = _get_class_lines(lines, idx)
                for i in range(class_lines[0], class_lines[1] + 1):
                    lines_to_remove.add(i)
                modified = True
            elif issue_type == "unused_attribute" or issue_type == "unused_import":
                lines[idx] = _comment_out_line(line)
                modified = True
            elif issue_type in ("unreachable_after", "unreachable_else"):
                _get_indent(line)
                end_idx = _find_block_end(lines, idx)
                for i in range(idx, end_idx + 1):
                    if i not in lines_to_remove:
                        lines_to_remove.add(i)
                modified = True
            elif issue_type == "redundant_if":
                lines[idx] = _comment_out_line(line)
                modified = True
        except Exception as e:
            print(f"Error processing {path}:{line_num} - {e}")
            continue
    if lines_to_remove:
        lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
        lines = _cleanup_blank_lines(lines)
        modified = True
    if modified:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"Fixed: {path}")
            return True
        except Exception as e:
            print(f"Error writing {path}: {e}")
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(original_lines)
            return False
    return False


def _comment_out_variable(line: str, name: str) -> str:
    indent = _get_indent(line)
    return f"{indent}# REMOVED: {line.strip()}\n"


def _comment_out_line(line: str) -> str:
    indent = _get_indent(line)
    return f"{indent}# REMOVED: {line.strip()}\n"


def _get_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _get_function_lines(lines: list[str], start_idx: int) -> tuple[int, int]:
    func_start = start_idx
    while func_start > 0:
        prev_line = lines[func_start - 1].strip()
        if prev_line.startswith("@"):
            func_start -= 1
        else:
            break
    start_line = lines[start_idx]
    indent = len(start_line) - len(start_line.lstrip())
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if line.strip() and not line.strip().startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent:
                break
        end_idx += 1
    return func_start, end_idx - 1


def _get_class_lines(lines: list[str], start_idx: int) -> tuple[int, int]:
    class_start = start_idx
    while class_start > 0:
        prev_line = lines[class_start - 1].strip()
        if prev_line.startswith("@"):
            class_start -= 1
        else:
            break
    start_line = lines[start_idx]
    indent = len(start_line) - len(start_line.lstrip())
    end_idx = start_idx + 1
    while end_idx < len(lines):
        line = lines[end_idx]
        if line.strip() and not line.strip().startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent:
                break
        end_idx += 1
    return class_start, end_idx - 1


def _find_block_end(lines: list[str], start_idx: int) -> int:
    indent = _get_indent(lines[start_idx])
    end_idx = start_idx
    while end_idx + 1 < len(lines):
        next_line = lines[end_idx + 1]
        if next_line.strip() and not next_line.strip().startswith("#"):
            next_indent = _get_indent(next_line)
            if len(next_indent) <= len(indent) and next_line.strip():
                break
        end_idx += 1
    return end_idx


def _cleanup_blank_lines(lines: list[str]) -> list[str]:
    cleaned = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)
    return cleaned


def main():
    if len(sys.argv) > 1:
        vulture_file = sys.argv[1]
        try:
            with open(vulture_file) as f:
                vulture_output = f.readlines()
        except FileNotFoundError:
            print(f"Error: File not found: {vulture_file}")
            sys.exit(1)
    else:
        print("Reading Vulture output from stdin...")
        vulture_output = sys.stdin.readlines()
    if not vulture_output:
        print("No input provided.")
        sys.exit(0)
    issues_by_file = parse_vulture_output(vulture_output)
    if not issues_by_file:
        print("No issues found to fix.")
        sys.exit(0)
    print(f"Found issues in {len(issues_by_file)} files.")
    print("\nThe following files will be modified:")
    for path in issues_by_file:
        print(f"  {path}: {len(issues_by_file[path])} issues")
    response = input("\nProceed with fixes? (y/N): ").strip().lower()
    if response not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)
    fixed_count = 0
    for path, issues in issues_by_file.items():
        if fix_file(path, issues):
            fixed_count += 1
    print(f"\nDone! Fixed {fixed_count} files.")


if __name__ == "__main__":
    raise SystemExit(main())
