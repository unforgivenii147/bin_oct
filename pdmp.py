#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXCLUDED_NAMES: set[str] = {"tmp", "cache", "bin", ".git", "etc", "config", "var"}
EXCLUDED_PATH_COMPONENTS: set[str] = {".git", "tmp", "etc", "var", "config"}


def is_excluded(path: Path, root_path: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return True
    try:
        relative_parts = path.relative_to(root_path).parts
        if any(part in EXCLUDED_PATH_COMPONENTS for part in relative_parts):
            return True
    except ValueError:
        pass
    return bool(path.name.startswith("mc") and path.parent.name == "tmp")


def delete_empty_dirs_iterative(
    root: Path, dry_run: bool = False, verbose: bool = False
) -> tuple[int, list[Path]]:
    removed_count: int = 0
    removed_dirs_list: list[Path] = []
    dirs_to_visit: list[Path] = [d for d in root.rglob("*") if d.is_dir()]
    dirs_to_visit.sort(key=lambda p: len(p.parts), reverse=True)
    if root.is_dir():
        dirs_to_visit.append(root)
    for path in dirs_to_visit:
        if not path.is_dir():
            continue
        if is_excluded(path, root):
            if verbose:
                print(f"Skipping excluded directory: {path.relative_to(root)}")
            continue
        try:
            if not any(
                entry for entry in path.iterdir() if entry.is_dir() or entry.is_file()
            ):
                if verbose:
                    print(f"Empty directory found: {path.relative_to(root)}")
                if not dry_run:
                    path.rmdir()
                    removed_count += 1
                    removed_dirs_list.append(path)
                    if verbose:
                        print(f"  --> Removed: {path.relative_to(root)}")
                else:
                    print(f"  (Dry Run) Would remove: {path.relative_to(root)}")
        except PermissionError:
            print(
                f"[ERROR] Permission denied for: {path.relative_to(root)}",
                file=sys.stderr,
            )
        except OSError as e:
            print(
                f"[ERROR] Could not process {path.relative_to(root)}: {e}",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[ERROR] An unexpected error occurred with {path.relative_to(root)}: {e}",
                file=sys.stderr,
            )
    return removed_count, removed_dirs_list


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and remove empty directories, excluding specified ones."
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="The root directory to start scanning from (default: current working directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run: show what would be deleted without actually deleting.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output, showing skipped and found directories.",
    )
    args = parser.parse_args()
    root_path = args.path.resolve()
    if not root_path.is_dir():
        print(
            f"Error: The provided path '{root_path}' is not a valid directory.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.dry_run:
        print("--- DRY RUN MODE (no changes will be made) ---")
    removed_count, removed_dirs_list = delete_empty_dirs_iterative(
        root_path, dry_run=args.dry_run, verbose=args.verbose
    )
    if removed_count > 0:
        if args.dry_run:
            print(f"Would have removed {removed_count} empty directories:")
        else:
            print(f"removed {removed_count}")
        for d_path in sorted(removed_dirs_list):
            print(f"- {d_path.relative_to(root_path)}")
    else:
        print("No empty dir.")


if __name__ == "__main__":
    raise SystemExit(main())
