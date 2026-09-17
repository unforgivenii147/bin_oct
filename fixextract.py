#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def fix_mis_extracted(root_dir: Path, dry_run: bool = True, verbose: bool = True):
    fixed = 0
    for dir_path in sorted(
        root_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True
    ):
        if not dir_path.is_dir():
            continue
        contents = list(dir_path.iterdir())
        if len(contents) != 1:
            continue
        file_in_dir = contents[0]
        if not file_in_dir.is_file():
            continue
        if file_in_dir.name != dir_path.name:
            continue
        parent = dir_path.parent
        target = parent / dir_path.name
        if verbose:
            print(f"\n📂 Found: {dir_path}/")
            print(f"   File: {file_in_dir}")
            print(f"   Target: {target}")
        if target.exists():
            if target.is_dir():
                if not dry_run:
                    backup_dir = parent / (dir_path.name + ".old")
                    shutil.move(str(dir_path), str(backup_dir))
                    shutil.move(str(backup_dir / dir_path.name), str(target))
                    backup_dir.rmdir()
                    if verbose:
                        print(f"   ✅ Replaced directory with file: {target}")
                    fixed += 1
                else:
                    print(f"   🔄 Would replace directory {dir_path}/ with file")
            elif not dry_run:
                target.unlink()
                shutil.move(str(file_in_dir), str(target))
                dir_path.rmdir()
                if verbose:
                    print(f"   ✅ Replaced file: {target}")
                fixed += 1
            else:
                print(f"   🔄 Would replace existing file: {target}")
        elif not dry_run:
            shutil.move(str(file_in_dir), str(target))
            dir_path.rmdir()
            if verbose:
                print(f"   ✅ Moved: {file_in_dir} -> {target}")
            fixed += 1
        else:
            print(f"   🔄 Would move: {file_in_dir} -> {target}")
    return fixed


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix directories containing a file with the same name (mis-extracted .zst files)"
    )
    parser.add_argument("-d", "--dir", default=".", help="Root directory to scan")
    parser.add_argument(
        "--fix", action="store_true", help="Apply fixes (default: dry-run)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    root = Path(args.dir).resolve()
    if not root.exists():
        print(f"❌ Error: {root} does not exist")
        sys.exit(1)
    print(f"🔍 Scanning: {root}")
    if not args.fix:
        print("🔍 DRY RUN – no changes will be made\n")
    else:
        print("🔧 Fixing mis-extracted files...\n")
    fixed = fix_mis_extracted(root, dry_run=not args.fix, verbose=args.verbose)
    print(f"\n📊 Summary: {fixed} issue(s) processed.")
    if not args.fix:
        print("💡 Run with --fix to apply changes.")


if __name__ == "__main__":
    raise SystemExit(main())
