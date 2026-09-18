#!/data/data/com.termux/files/home/.local/bin/python
"""Remove files listed in a manifest file from the current (top-level) folder.
Defaults to 'list.txt' if no argument is provided, and deletes the list file
afterward."""

import sys
from pathlib import Path

DEFAULT_LIST = "list.txt"


def main() -> int:
    list_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LIST
    list_file = Path(list_name)

    if not list_file.is_file():
        print(f"Error: list file not found: {list_file}", file=sys.stderr)
        return 1

    cwd = Path.cwd()
    removed = 0
    missing = 0

    for raw_line in list_file.read_text().splitlines():
        name = raw_line.strip()
        if not name or name.startswith("#"):
            continue

        target = cwd / name

        # Safety: only operate on top-level entries directly under cwd
        if target.parent.resolve() != cwd.resolve():
            print(f"skipping (not top-level): {name}", file=sys.stderr)
            continue

        if target.is_file():
            target.unlink()
            print(f"removed: {name}")
            removed += 1
        else:
            print(f"not found: {name}", file=sys.stderr)
            missing += 1

    # Remove the list file itself (only if it's the top-level one we read)
    if list_file.resolve().parent == cwd.resolve():
        list_file.unlink()
        print(f"removed list file: {list_file.name}")

    print(f"\nDone. {removed} removed, {missing} not found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
