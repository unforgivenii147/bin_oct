#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import re
import sys


def parse_vulture_output(path):
    skip_dirs_fixes = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                match = re.match(
                    r'^(.+?):(\d+):\s+unused variable\s+[\'"]SKIP_DIRS[\'"]', line
                )
                if match:
                    filename = match.group(1)
                    line_num = int(match.group(2))
                    if filename not in skip_dirs_fixes:
                        skip_dirs_fixes[filename] = []
                    if line_num not in skip_dirs_fixes[filename]:
                        skip_dirs_fixes[filename].append(line_num)
    except FileNotFoundError:
        print(f"Error: File not found: {path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    return skip_dirs_fixes


def find_file(filename, search_root="."):
    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if filename in files:
            return os.path.join(root, filename)
    return None


def main():
    if len(sys.argv) != 2:
        print("Usage: python comment_skip_dirs.py <vulture_output_file>")
        print("Example: python comment_skip_dirs.py vulture_output.txt")
        sys.exit(1)
    vulture_file = sys.argv[1]
    print(f"Reading vulture output from: {vulture_file}")
    skip_dirs_fixes = parse_vulture_output(vulture_file)
    if not skip_dirs_fixes:
        print("No SKIP_DIRS entries found in vulture output.")
        sys.exit(0)
    print(f"Found {len(skip_dirs_fixes)} files with unused SKIP_DIRS\n")
    fixed = 0
    skipped = 0
    not_found = 0
    for filename, line_numbers in skip_dirs_fixes.items():
        path = find_file(filename)
        if not path:
            print(f"✗ Not found: {filename}")
            not_found += 1
            continue
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            modified = False
            for line_num in sorted(line_numbers):
                if 1 <= line_num <= len(lines):
                    line = lines[line_num - 1]
                    if "SKIP_DIRS" in line and not line.lstrip().startswith("#"):
                        indent = len(line) - len(line.lstrip())
                        content = line.lstrip()
                        lines[line_num - 1] = " " * indent + "# " + content
                        print(f"✓ {filename}:{line_num}")
                        fixed += 1
                        modified = True
                    else:
                        print(
                            f"⏭ {filename}:{line_num} (already commented or no SKIP_DIRS)"
                        )
                        skipped += 1
            if modified:
                with open(path, "w") as f:
                    f.writelines(lines)
        except Exception as e:
            print(f"✗ Error in {filename}: {e}")
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Fixed: {fixed}")
    print(f"  Skipped: {skipped}")
    print(f"  Not found: {not_found}")


if __name__ == "__main__":
    raise SystemExit(main())
