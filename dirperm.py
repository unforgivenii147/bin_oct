#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from tqdm import tqdm

SKIP_DIRS = {".git", ".ruff_cache", "__pycache__"}


def should_skip_dir(dirname):
    return dirname in SKIP_DIRS


def walk_all(root_path="."):
    root = Path(root_path)

    def walk(p: Path):
        if should_skip_dir(p.name):
            return
        yield ("dir", str(p))
        try:
            for item in p.iterdir():
                if item.is_dir():
                    yield from walk(item)
                elif item.is_file():
                    if item.is_symlink():
                        continue
                    yield ("file", str(item))
        except PermissionError:
            pass

    yield from walk(root)


def walk_dirs(root_path="."):
    for item_type, path in walk_all(root_path):
        if item_type == "dir":
            yield path


def walk_files(root_path="."):
    for item_type, path in walk_all(root_path):
        if item_type == "file":
            yield path


def has_shebang(path):
    try:
        with open(path, "rb") as f:
            first_line = f.readline()
            return first_line.startswith(b"#!")
    except OSError:
        return False


def is_executable(path):
    try:
        return os.access(path, os.X_OK)
    except:
        return False


def get_current_mode(path):
    try:
        return stat.S_IMODE(Path(path).stat().st_mode)
    except:
        return None


def determine_dir_target_mode():
    return 509


def determine_file_target_mode(path):
    if is_executable(path):
        return None
    parent_dir = Path(path).parent.name
    if has_shebang(path) or parent_dir == "bin":
        return 493
    return 420


def analyze_item(item_type, path):
    if item_type == "dir":
        target_mode = determine_dir_target_mode(path)
    else:
        target_mode = determine_file_target_mode(path)
    if target_mode is None:
        return ("skip_executable", path, None, None)
    current_mode = get_current_mode(path)
    if current_mode is None:
        return ("error", path, None, target_mode)
    if current_mode != target_mode:
        return ("change", path, current_mode, target_mode)
    else:
        return ("skip_correct", path, current_mode, target_mode)


def process_item(path, target_mode, dry_run=False):
    if dry_run:
        return True
    try:
        Path(path).chmod(target_mode)
        return True
    except Exception as e:
        print(f"Error: {path}: {e}")
        return False


def apply_changes(stats, dry_run=False):
    all_changes = (
        stats["dirs_to_change"]
        + stats["files_make_executable"]
        + stats["files_set_standard"]
    )
    if not all_changes:
        print("\nNo changes needed!")
        return (0, 0)
    print(f"\nApplying changes to {len(all_changes)} items...")
    success = 0
    failed = 0
    for path, _current, target in tqdm(
        all_changes, desc="Changing permissions", unit="items"
    ):
        if process_item(path, target, dry_run):
            success += 1
        else:
            failed += 1
    return (success, failed)


def print_report(stats, success=None, failed=None):
    total_items = stats["total_dirs"] + stats["total_files"]
    total_changes = (
        len(stats["dirs_to_change"])
        + len(stats["files_make_executable"])
        + len(stats["files_set_standard"])
    )
    print(f"\n{'=' * 40}")
    print("Scan Summary:")
    print(f"  Total items scanned: {total_items}")
    print(f"    Directories: {stats['total_dirs']}")
    print(f"    Files: {stats['total_files']}")
    print("\nDirectory Permissions:")
    print(f"  → Will set to 0775: {len(stats['dirs_to_change'])}")
    print(f"  ✓ Already correct (0775): {len(stats['dirs_correct'])}")
    print("\nFile Permissions:")
    print(f"  ⊘ Already executable (skipped): {len(stats['files_skip_executable'])}")
    print(f"  → Will make executable (+x): {len(stats['files_make_executable'])}")
    print(f"  → Will set to standard (0644): {len(stats['files_set_standard'])}")
    print(f"  ✓ Already correct: {len(stats['files_skip_correct'])}")
    print(f"\nTotal changes needed: {total_changes}")
    if stats["errors"]:
        print(f"  ✗ Errors during analysis: {len(stats['errors'])}")
    if success is not None:
        print(f"\n{'=' * 40}")
        print("Results:")
        print(f"  ✓ Changes successful: {success}")
        if failed:
            print(f"  ✗ Changes failed: {failed}")
    print(f"{'=' * 40}")


def show_examples(stats, num=5):
    if stats["dirs_to_change"]:
        print("\nExamples of directories to change to 0775:")
        for path, current, target in stats["dirs_to_change"][:num]:
            print(f"  {oct(current)} -> {oct(target)}  {path}")
        if len(stats["dirs_to_change"]) > num:
            print(f"  ... and {len(stats['dirs_to_change']) - num} more")
    if stats["files_make_executable"]:
        print("\nExamples of files to make executable (+x):")
        for path, current, target in stats["files_make_executable"][:num]:
            print(f"  {oct(current)} -> {oct(target)}  {path}")
        if len(stats["files_make_executable"]) > num:
            print(f"  ... and {len(stats['files_make_executable']) - num} more")
    if stats["files_set_standard"]:
        print("\nExamples of files to set to 0644:")
        for path, current, target in stats["files_set_standard"][:num]:
            print(f"  {oct(current)} -> {oct(target)}  {path}")
        if len(stats["files_set_standard"]) > num:
            print(f"  ... and {len(stats['files_set_standard']) - num} more")
    if stats["files_skip_executable"]:
        print("\nExamples of skipped files (already executable):")
        for path in stats["files_skip_executable"][:num]:
            print(f"  {path}")
        if len(stats["files_skip_executable"]) > num:
            print(f"  ... and {len(stats['files_skip_executable']) - num} more")


def main():
    parser = argparse.ArgumentParser(
        description="Fix directory and file permissions with smart rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"\nRules for directories:\n  - All directories: set to 0775 (rwxrwxr-x)\n\nRules for files:\n  - Files that are already executable: no changes\n  - Files with shebang (#!) or in 'bin' directory: set to 0755 (rwxr-xr-x)\n  - All other files: set to 0644 (rw-r--r--)\n\nSkipped directories: {
            ', '.join(sorted(SKIP_DIRS))
        }\n\nExamples:\n  %(prog)s                    # Process current directory\n  %(prog)s /path/to/project   # Process specific path\n  %(prog)s . --dry-run        # Preview changes\n  %(prog)s . --show-examples  # Show examples of changes\n  %(prog)s . --dirs-only      # Only process directories\n  %(prog)s . --files-only     # Only process files\n        ",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Root path to start from (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually changing permissions",
    )
    parser.add_argument(
        "--show-examples",
        action="store_true",
        help="Show example files/directories that would be changed",
    )
    parser.add_argument(
        "--dirs-only", action="store_true", help="Only process directories, skip files"
    )
    parser.add_argument(
        "--files-only", action="store_true", help="Only process files, skip directories"
    )
    args = parser.parse_args()
    print(f"Skip directories: {', '.join(sorted(SKIP_DIRS))}")
    if args.dirs_only:
        print("Mode: Directories only")
    elif args.files_only:
        print("Mode: Files only")
    if args.dry_run:
        print("DRY RUN - No changes will be made\n")
    if args.dirs_only:
        print("Scanning directories...")
        dirs = list(tqdm(walk_dirs(args.path), desc="Scanning dirs", unit="dirs"))
        items = [("dir", d) for d in dirs]
    elif args.files_only:
        print("Scanning files...")
        files = list(tqdm(walk_files(args.path), desc="Scanning files", unit="files"))
        items = [("file", f) for f in files]
    else:
        items = walk_all(args.path)
    stats = {
        "total_dirs": 0,
        "total_files": 0,
        "dirs_to_change": [],
        "dirs_correct": [],
        "files_skip_executable": [],
        "files_skip_correct": [],
        "files_make_executable": [],
        "files_set_standard": [],
        "errors": [],
    }
    item_list = list(items) if not isinstance(items, list) else items
    for item_type, path in tqdm(item_list, desc="Analyzing", unit="items"):
        if item_type == "dir":
            stats["total_dirs"] += 1
        else:
            stats["total_files"] += 1
        status, path, current, target = analyze_item(item_type, path)
        if status == "skip_executable":
            stats["files_skip_executable"].append(path)
        elif status == "skip_correct":
            if item_type == "dir":
                stats["dirs_correct"].append(path)
            else:
                stats["files_skip_correct"].append(path)
        elif status == "change":
            if item_type == "dir":
                stats["dirs_to_change"].append((path, current, target))
            elif target == 493:
                stats["files_make_executable"].append((path, current, target))
            else:
                stats["files_set_standard"].append((path, current, target))
        elif status == "error":
            stats["errors"].append(path)
    print_report(stats)
    if args.show_examples:
        show_examples(stats)
    if not args.dry_run:
        success, failed = apply_changes(stats, dry_run=False)
        if success is not None:
            print(f"\n{'=' * 40}")
            print("Final Results:")
            print(f"  ✓ Changes applied successfully: {success}")
            if failed:
                print(f"  ✗ Failed changes: {failed}")
            print(f"{'=' * 40}")
    else:
        total_changes = (
            len(stats["dirs_to_change"])
            + len(stats["files_make_executable"])
            + len(stats["files_set_standard"])
        )
        if total_changes > 0:
            print(f"\nWould apply {total_changes} changes")


if __name__ == "__main__":
    raise SystemExit(main())
