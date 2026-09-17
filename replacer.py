#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dh import is_binary

MAX_CONTEXT_DISPLAY = 3


def process_file(
    path: Path,
    search_text: str,
    replace_text: str = "",
    remove_mode: bool = False,
    dry_run: bool = False,
) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
        pattern = re.compile(re.escape(search_text))
        if not pattern.search(content):
            return False
        if remove_mode:
            replacement = ""
        else:
            replacement = replace_text
        if dry_run:
            matches = list(pattern.finditer(content))
            print(f"[DRY RUN] Found {len(matches)} match(es) in {path}")
            for i, match in enumerate(matches[:MAX_CONTEXT_DISPLAY]):
                start = max(0, match.start() - 20)
                end = min(len(content), match.end() + 20)
                context = content[start:end].replace("\n", " ").strip()
                print(f"  Match {i + 1}: ...{context}...")
            if len(matches) > MAX_CONTEXT_DISPLAY:
                print(f"  ... and {len(matches) - MAX_CONTEXT_DISPLAY} more matches")
        else:
            new_content = pattern.sub(replacement, content)
            path.write_text(new_content, encoding="utf-8")
            print(f"Updated: {path}")
        return True
    except (UnicodeDecodeError, PermissionError) as e:
        print(f"Skipping {path}: {e}", file=sys.stderr)
        return False
    except IsADirectoryError:
        return False
    except OSError as e:
        print(f"Error processing {path}: {e}", file=sys.stderr)
        return False


def replace_in_files(
    search_text: str,
    replace_text: str = "",
    remove_mode: bool = False,
    target_file: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    files_processed = 0
    files_changed = 0
    if target_file:
        path = Path(target_file)
        if not path.is_file() or path.is_symlink():
            print(f"Error: {target_file} is not a valid file", file=sys.stderr)
            return 0, 0
        print(f"Processing file: {target_file}")
        if process_file(path, search_text, replace_text, remove_mode, dry_run):
            files_changed += 1
        return 1, files_changed
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
        for filename in files:
            path = Path(root) / filename
            if path.is_symlink() or is_binary(path):
                continue
            files_processed += 1
            if process_file(path, search_text, replace_text, remove_mode, dry_run):
                files_changed += 1
            if files_processed % 100 == 0:
                print(f"Processed {files_processed} files...", end="\r")
    return files_processed, files_changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively replace or remove text in files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  %(prog)s 'old_text' 'new_text'    # Replace text\n"
        "  %(prog)s -r 'text_to_remove'      # Remove text\n"
        "  %(prog)s 'text' -r                # Remove text (alternative syntax)\n"
        "  %(prog)s 'text' --dry-run         # Preview changes",
    )
    parser.add_argument(
        "search",
        help="Text to search for",
    )
    parser.add_argument(
        "replace",
        nargs="?",
        default="",
        help="Replacement text (optional, defaults to empty string)",
    )
    parser.add_argument(
        "-r",
        "--remove",
        action="store_true",
        help="Remove the search text instead of replacing it",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without applying them"
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Process only the specified file instead of recursive directory search",
    )
    args = parser.parse_args()
    if args.remove:
        args.replace = ""
    search_text = args.search
    replace_text = args.replace
    if args.remove:
        action = f"REMOVING '{search_text}'"
    elif replace_text:
        action = f"REPLACING '{search_text}' WITH '{replace_text}'"
    else:
        action = f"REMOVING '{search_text}'"
    if args.dry_run:
        print("--- RUNNING IN DRY RUN MODE (No files will be modified) ---")
    print(f"--- {action} ---")
    files_processed, files_changed = replace_in_files(
        search_text,
        replace_text,
        remove_mode=args.remove,
        target_file=args.file,
        dry_run=args.dry_run,
    )
    print(
        f"\n--- Complete: Processed {files_processed} files, modified {files_changed} files ---"
    )


if __name__ == "__main__":
    raise SystemExit(main())
