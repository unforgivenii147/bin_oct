#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
from pathlib import Path


def remove_second_if_first_exists(root: Path, dry_run: bool = True) -> None:
    removed = 0
    checked = 0
    for json_path in root.glob("*.json"):
        checked += 1
        txt_path = json_path.with_suffix(".txt")
        if txt_path.exists():
            print(f"[MATCH] {json_path}  ->  {txt_path}")
            if not dry_run:
                try:
                    txt_path.unlink()
                    print(f"[REMOVED] {txt_path}")
                    removed += 1
                except Exception as e:
                    print(f"[ERROR] Could not remove {txt_path}: {e}")
            else:
                print(f"[DRY RUN] Would remove {txt_path}")
    print("\n--- Summary ---")
    print(f"Checked: {checked}")
    print(f"Removed: {removed}" if not dry_run else "Dry run only. No files removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove .txt files if a .json file with the same name exists."
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Actually delete files (default is dry run).",
    )
    args = parser.parse_args()
    cwd = Path.cwd()
    remove_second_if_first_exists(cwd, dry_run=not args.apply)
