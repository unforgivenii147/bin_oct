#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

from dh import mpf3, unique_path


def rename_item_to_lowercase(
    path: Path, dry_run: bool = False, verbose: bool = False
) -> tuple[Path, Path] | None:
    if not path.exists():
        if verbose:
            print(f"Warning: {path} does not exist. Skipping.", file=sys.stderr)
        return None
    new_name_lower = path.name.lower()
    if new_name_lower == path.name:
        if verbose:
            print(f"Skipping {path.name}: already lowercase.")
        return None
    new_path_candidate = path.parent / new_name_lower
    if new_path_candidate.exists() and new_path_candidate != path:
        new_path = unique_path(new_path_candidate)
        if verbose:
            print(
                f"Note: Target {new_path_candidate.name} already exists. Using unique path: {new_path.name}"
            )
    else:
        new_path = new_path_candidate
    if dry_run:
        print(f"DRY RUN: Would rename '{path}' to '{new_path}'")
        return (path, new_path)
    try:
        Path(path).rename(new_path)
        if verbose:
            print(f"Renamed '{path.name}' to '{new_path.name}'")
        return (path, new_path)
    except OSError as e:
        print(
            f"Error renaming '{path.name}' to '{new_path.name}': {e}", file=sys.stderr
        )
        return None
    except Exception as e:
        print(f"An unexpected error occurred for '{path.name}': {e}", file=sys.stderr)
        return None


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")
        print("--- DRY RUN MODE: No changes will be made ---")
    verbose = "--verbose" in args
    if verbose:
        args.remove("--verbose")
    if args:
        paths_to_process = [Path(p) for p in args]
    else:
        all_items = list(cwd.rglob("*"))
        paths_to_process = sorted(all_items, key=lambda p: len(p.parts), reverse=True)
    if not paths_to_process:
        print("No files or directories found to process.")
        return
    print(f"Found {len(paths_to_process)} items to potentially rename.")
    process_func_with_flags = partial(
        rename_item_to_lowercase, dry_run=dry_run, verbose=verbose
    )
    results = mpf3(process_func_with_flags, paths_to_process)
    if dry_run:
        print("--- DRY RUN COMPLETE ---")
    else:
        renamed_count = sum(1 for r in results if r is not None)
        print(f"\nSummary: Renamed {renamed_count} items.")


if __name__ == "__main__":
    raise SystemExit(main())
