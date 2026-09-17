#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    apply_changes = False
    filtered_args = []
    for arg in args:
        if arg in ("-a", "--apply"):
            apply_changes = True
        else:
            filtered_args.append(arg)
    if len(filtered_args) != 2:
        print(
            "Usage: python3 remove_lines.py <input_file> <text_to_remove> [-a|--apply]"
        )
        print("\nOptions:")
        print("  -a, --apply    Actually modify the file (default is dry-run)")
        sys.exit(1)
    input_file = Path(filtered_args[0])
    text_to_remove = filtered_args[1]
    if not input_file.exists():
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)
    lines = input_file.read_text(encoding="utf-8").splitlines()
    filtered_lines = [line for line in lines if text_to_remove not in line]
    removed_count = len(lines) - len(filtered_lines)
    print(f"Lines containing '{text_to_remove}': {removed_count}")
    print(f"Remaining lines: {len(filtered_lines)}")
    if removed_count > 0:
        print("\nLines that would be removed:")
        print("-" * 40)
        for line in lines:
            if text_to_remove in line:
                print(f"  - {line}")
        print("-" * 40)
    if apply_changes:
        input_file.write_text("\n".join(filtered_lines) + "\n", encoding="utf-8")
        print(f"\n✅ Changes applied to '{input_file}'")
    else:
        print(f"\n⚠️  Dry run - no changes made. Use -a or --apply to apply changes.")


if __name__ == "__main__":
    main()
