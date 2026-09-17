#!/data/data/com.termux/files/home/.local/bin/python
import argparse
import multiprocessing as mp
import re
import sys
from pathlib import Path

INVALID_ESCAPE_PATTERN = re.compile(r'(?<!\\)\\(?![\\\'"abfnrtvNuUx0-7\n])')


def process_file(path: Path, autofix: bool = False) -> tuple[Path, int, bool]:
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return (path, 0, False)
    matches = list(INVALID_ESCAPE_PATTERN.finditer(content))
    count = len(matches)
    if count == 0:
        return (path, 0, False)
    if autofix:
        fixed_content = INVALID_ESCAPE_PATTERN.sub(r"\\\\", content)
        path.write_text(fixed_content, encoding="utf-8")
        return (path, count, True)
    return (path, count, False)


def main():
    parser = argparse.ArgumentParser(
        description="Recursively check/fix invalid escape sequences in Python files."
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically fix found invalid escape sequences by escaping backslashes.",
    )
    args = parser.parse_args()
    current_dir = Path.cwd()
    py_files = [p for p in current_dir.rglob("*.py") if p.is_file()]
    if not py_files:
        print("No Python files found.")
        return
    num_workers = 8
    async_results = []
    with mp.Pool(processes=num_workers) as pool:
        for path in py_files:
            res = pool.apply_async(process_file, args=(path, args.autofix))
            async_results.append(res)
        results = [res.get() for res in async_results]
    total_issues = 0
    flagged_files = 0
    print(f"Scanning {len(py_files)} Python files using {num_workers} workers...\n")
    for path, count, fixed in results:
        if count > 0:
            flagged_files += 1
            total_issues += count
            rel_path = path.relative_to(current_dir)
            status = "FIXED" if fixed else "FOUND"
            print(f"[{status}] {rel_path}: {count} invalid escape sequence(s)")
    print("\n--- Summary ---")
    print(f"Files scanned: {len(py_files)}")
    print(f"Files with issues: {flagged_files}")
    print(f"Total issues: {total_issues}")
    if flagged_files > 0 and not args.autofix:
        print(
            "\nRun with -a or --autofix to automatically double-escape invalid backslashes."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
