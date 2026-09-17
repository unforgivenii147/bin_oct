#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

PRINT_PATTERN = re.compile(r"^\s*print\s+(?!\()(.+)$")
PRINT_BARE_PATTERN = re.compile(r"^\s*print\s*$")
EXCEPT_PATTERN = re.compile(r"^\s*except\s+(\S+)\s*,\s*(\S+)\s*:")


def fix_py2_to_py3_all(line):
    original = line
    line = line.replace("xrange(", "range(")
    line = line.replace("raw_input(", "input(")
    m = EXCEPT_PATTERN.match(line.strip())
    if m:
        indent = line[: len(line) - len(line.lstrip())]
        exc_type, exc_var = m.group(1), m.group(2)
        line = f"{indent}except {exc_type} as {exc_var}:\n"
    return line, line != original


def fix_print_statements(text: str) -> tuple[str, bool]:
    lines = text.splitlines(True)
    new_lines = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if PRINT_BARE_PATTERN.match(stripped):
            indent = line[: len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}print()\n")
            changed = True
            continue
        m = PRINT_PATTERN.match(stripped)
        if m:
            expr = m.group(1)
            indent = line[: len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}print({expr})\n")
            changed = True
            continue
        new_lines.append(line)
    return "".join(new_lines), changed


def apply_all_fixes(text: str):
    lines = text.splitlines(True)
    new_lines = []
    changed = False
    for line in lines:
        new_line, c1 = fix_py2_to_py3_all(line)
        new_line2, c2 = fix_print_statements(new_line)
        changed = changed or c1 or c2
        new_lines.append(new_line2)
    return "".join(new_lines), changed


changed_files = []
error_files = []


def process_file(path: Path, force=False, apply_all=False) -> None:
    path = Path(path)
    try:
        original = path.read_text(encoding="utf-8")
        if apply_all:
            fixed, changed = apply_all_fixes(original)
        else:
            fixed, changed = fix_print_statements(original)
        if changed:
            if not force:
                backup_path = path.with_suffix(path.suffix + ".bak")
                shutil.copy2(path, backup_path)
            path.write_text(fixed, encoding="utf-8")
            changed_files.append(str(path))
    except Exception as e:
        error_files.append((str(path), str(e)))


def scan_and_fix(root: Path, force, apply_all) -> None:
    for f in root.rglob("*.py"):
        process_file(f, force=force, apply_all=apply_all)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix Python2 print statements and optionally apply all Py2→Py3 conversions."
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite original files (no .bak backups)",
    )
    parser.add_argument(
        "-a", "--all", action="store_true", help="Apply all Python2→Python3 fixes"
    )
    args = parser.parse_args()
    if not any(vars(args).values()):
        args.force = True
        args.all = True
    root = Path.cwd()
    scan_and_fix(root, force=args.force, apply_all=args.all)
    print("\n=== SUMMARY ===")
    print(f"Files changed: {len(changed_files)}")
    for f in changed_files:
        print("  -", f)
    print(f"\nFiles with errors: {len(error_files)}")
    for f, e in error_files:
        print(f"  - {f}: {e}")
