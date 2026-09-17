#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def is_blank_line(line: str):
    return line.strip() == ""


def find_duplicates(path: Path, skip_blanks: bool = True):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        duplicates = []
        i = 0
        while i < len(lines) - 1:
            current = lines[i]
            next_line = lines[i + 1]
            if skip_blanks and (is_blank_line(current) or is_blank_line(next_line)):
                i += 1
                continue
            if current == next_line:
                duplicates.append((i + 1, current.rstrip("\n")))
                i += 1
            i += 1
        return duplicates
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return []


def remove_duplicates(lines: list[str], duplicates):
    lines_copy = lines.copy()
    removed = 0
    for line_num, _ in reversed(duplicates):
        idx = line_num + 1 - removed - 1
        if 0 <= idx < len(lines_copy):
            del lines_copy[idx]
            removed += 1
    return lines_copy


def process_file(
    path,
    duplicates,
    dry_run: bool = False,
    auto_yes=False,
    skip_blanks: bool = True,
):
    if not duplicates:
        return False, auto_yes
    print(f"\n{'[DRY RUN] ' if dry_run else ''}📄 {path.name}")
    for line_num, content in duplicates:
        print(f"  Line {line_num}: {content}")
        print(f"  Line {line_num + 1}: {content}")
    if dry_run:
        return False, auto_yes
    if not auto_yes:
        response = (
            input(f"\n  Remove duplicates from {path.name}? (y/n/a/q): ")
            .strip()
            .lower()
        )
        if response == "q":
            sys.exit(0)
        elif response == "a":
            auto_yes = True
            should_fix = True
        elif response == "y":
            should_fix = True
        else:
            should_fix = False
    else:
        should_fix = True
    if should_fix:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = remove_duplicates(lines, duplicates)
        backup = path.with_suffix(path.suffix + ".bak")
        with open(backup, "w", encoding="utf-8") as f:
            f.writelines(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"  ✅ Fixed (backup: {backup.name})")
        return True, auto_yes
    print("  ⏭️  Skipped")
    return False, auto_yes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and remove sequential duplicate lines in Python files",
        epilog="Blank lines are ignored by default.",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Automatically answer yes to all prompts",
    )
    parser.add_argument(
        "--include-blanks",
        "-b",
        action="store_true",
        help="Include blank lines when checking for duplicates (default: skip blanks)",
    )
    args = parser.parse_args()
    skip_blanks = not args.include_blanks
    print("-" * 40)
    if args.dry_run:
        print("🔍 DRY RUN MODE - No files will be modified")
    print(
        f"📝 {'Ignoring' if skip_blanks else 'Including'} blank lines in duplicate detection"
    )
    print("-" * 40)
    cwd = Path.cwd()
    py_files = get_pyfiles(cwd)
    files_with_dups = {}
    for py_file in py_files:
        dups = find_duplicates(py_file, skip_blanks)
        if dups:
            files_with_dups[py_file] = dups
    if not files_with_dups:
        print("\n✓ No non-blank sequential duplicates found!")
        return
    print(f"\nFound {len(files_with_dups)} file(s) with sequential duplicates\n")
    auto_yes = args.yes
    fixed_count = 0
    for path, dups in files_with_dups.items():
        fixed, auto_yes = process_file(path, dups, args.dry_run, auto_yes, skip_blanks)
        if fixed:
            fixed_count += 1
    print("\n" + "=" * 40)
    if args.dry_run:
        print("🔍 Dry run complete. Run without --dry-run to apply changes.")
    else:
        print(f"✅ Fixed {fixed_count} file(s)")
        print("💡 Backups saved with .bak extension")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user.")
        sys.exit(1)
