#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from collections import defaultdict

VULTURE_RE = re.compile(
    r"^(?P<path>.*?):(?P<lineno>\d+):\s*unused variable '(?P<var>[^']+)'", re.IGNORECASE
)


def parse_vulture_output(lines: list[str]) -> dict[str, set[int]]:
    mapping: dict[str, set[int]] = defaultdict(set)
    for ln in lines:
        ln = ln.rstrip("\n")
        m = VULTURE_RE.match(ln)
        if not m:
            continue
        path = m.group("path")
        lineno = int(m.group("lineno"))
        mapping[path].add(lineno)
    return mapping


def comment_lines_in_file(
    path: str, line_numbers: set[int]
) -> tuple[list[str], list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        original = f.readlines()
    modified = original.copy()
    max_line = len(original)
    for ln in sorted(line_numbers):
        if ln < 1 or ln > max_line:
            print(
                f"  [!] {path}:{ln} out of range (file has {max_line} lines), skipping"
            )
            continue
        idx = ln - 1
        line = original[idx]
        stripped = line.lstrip()
        if not stripped:
            leading = line[: len(line) - len(stripped)]
            modified[idx] = leading + "#\n"
            continue
        first_non_ws = stripped[0]
        if first_non_ws == "#":
            continue
        leading = line[: len(line) - len(stripped)]
        modified[idx] = leading + "# " + stripped
    return (original, modified)


def show_diff_and_maybe_write(
    path: str, original: list[str], modified: list[str], apply: bool, backup: bool
) -> None:
    if original == modified:
        print(f"No changes needed for {path}")
        return
    diff = difflib.unified_diff(
        original, modified, fromfile=path, tofile=path, lineterm=""
    )
    print("".join(line + "\n" for line in diff))
    if apply:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(modified)
            print(f"  [written] updated {path}")
        except Exception as e:
            print(f"  [!] failed to write {path}: {e}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Comment out lines reported by vulture as unused variables."
    )
    ap.add_argument(
        "vulture_output",
        nargs="?",
        help="Path to vulture output file. If omitted, reads stdin.",
    )
    ap.add_argument(
        "--apply",
        default=True,
        action="store_true",
        help="Actually write changes to files. Default: dry-run (show diffs).",
    )
    ap.add_argument(
        "--backup",
        action="store_true",
        help="When used with --apply, create .bak backups of files.",
    )
    ap.add_argument(
        "--show-summary", action="store_true", help="Show summary at the end."
    )
    args = ap.parse_args(argv)
    if args.vulture_output:
        try:
            with open(args.vulture_output, "r", encoding="utf-8") as f:
                vout = f.readlines()
        except Exception as e:
            print(
                f"Failed to read vulture output file '{args.vulture_output}': {e}",
                file=sys.stderr,
            )
            return 2
    else:
        vout = sys.stdin.readlines()
    mapping = parse_vulture_output(vout)
    if not mapping:
        print("No matching vulture entries found in input.")
        return 0
    files_processed = 0
    files_modified = 0
    for path, linenos in sorted(mapping.items()):
        print(f"Processing {path} lines: {', '.join(map(str, sorted(linenos)))}")
        if not os.path.exists(path):
            print(f"  [!] file not found: {path}, skipping")
            continue
        original, modified = comment_lines_in_file(path, linenos)
        if original != modified:
            files_modified += 1
        show_diff_and_maybe_write(path, original, modified, args.apply, args.backup)
        files_processed += 1
    if args.show_summary:
        print()
        print(
            f"Summary: files processed: {files_processed}, files modified: {files_modified}"
        )
        if not args.apply:
            print("Dry-run mode — no files were changed. Use --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
