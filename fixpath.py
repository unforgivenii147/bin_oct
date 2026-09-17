#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import glob
import os
import re


def fix_pattern_and_save(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        print(f"✗ Error reading {path}: {e}")
        return False
    pattern = "(def process_file\\([^)]*\\):)\\n(\\s+)([^\\n]+)\\n(\\s+)(path = Path\\(path\\))"

    def replace_func(match) -> str:
        func_def = match.group(1)
        indent = match.group(2)
        first_stmt = match.group(3)
        path_stmt = match.group(5)
        return f"{func_def}\n{indent}{path_stmt}\n{indent}{first_stmt}"

    fixed_content = re.sub(pattern, replace_func, original_content)
    if fixed_content != original_content:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(fixed_content)
            print(f"✓ Fixed: {path}")
            return True
        except Exception as e:
            print(f"✗ Error writing {path}: {e}")
            return False
    return False


def fix_all_python_files(directory_path: str = ".") -> None:
    python_files = glob.glob(os.path.join(directory_path, "**/*.py"), recursive=True)
    print(f"Scanning {len(python_files)} Python files...\n")
    fixed_count = 0
    for path in python_files:
        if fix_pattern_and_save(path):
            fixed_count += 1
    print(f"\n✓ Total files fixed: {fixed_count}")


if __name__ == "__main__":
    fix_all_python_files(".")
