#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import NamedTuple


class ProcessResult(NamedTuple):
    file: Path
    replacements: int
    status: str
    error: str | None = None


def normalize_separators(content: str) -> tuple[str, int]:
    pattern = r"(cprint|print)\s*\(\s*['\"](.)['\"](\s*\*\s*)(\d+)([^)]*)\)"
    replacement = "print('-'*42)"
    new_content, count = re.subn(pattern, replacement, content)
    return new_content, count


def process_file(args: tuple[Path, bool]) -> ProcessResult:
    path, autofix = args
    try:
        content = path.read_text(encoding="utf-8")
        new_content, replacements = normalize_separators(content)
        if replacements > 0 and autofix:
            path.write_text(new_content, encoding="utf-8")
        return ProcessResult(file=path, replacements=replacements, status="success")
    except Exception as e:
        return ProcessResult(file=path, replacements=0, status="error", error=str(e))


def find_python_files(paths: list[str]) -> list[Path]:
    if not paths:
        paths = ["."]
    all_files = set()
    for path_str in paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".py":
            all_files.add(path.resolve())
        elif path.is_dir():
            all_files.update(path.resolve().rglob("*.py"))
    return sorted(all_files)


def report_stats(results: list[ProcessResult], autofix: bool) -> None:
    total_files = len(results)
    total_replacements = sum(r.replacements for r in results)
    success_count = sum(1 for r in results if r.status == "success")
    modified_count = sum(1 for r in results if r.replacements > 0)
    cwd = Path.cwd()
    rel_results = [
        (
            r.file.relative_to(cwd)
            if cwd in r.file.parents or r.file == cwd
            else r.file,
            r,
        )
        for r in results
    ]
    mode = "AUTOFIX" if autofix else "DRY-RUN"
    print(f"\n[{mode}] {'File':<55} {'Replacements':<15} {'Status':<15}")
    print("-" * 40)
    for rel_path, result in rel_results:
        status_str = "✓ Success" if result.status == "success" else "✗ Error"
        if result.error:
            status_str += f": {result.error[:20]}"
        print(f"{rel_path!s:<55} {result.replacements:<15} {status_str:<15}")
    print("-" * 40)
    print(f"Total files:        {total_files}")
    print(f"Files would change: {modified_count}")
    print(f"Total replacements: {total_replacements}")
    print(f"Successful:         {success_count}")
    print(f"Errors:             {total_files - success_count}")
    if not autofix and modified_count > 0:
        print(
            f"\n💡 Run with --autofix (or -a) to apply {total_replacements} change(s)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize print separators in Python files.",
        epilog="Examples:\n"
        "  %(prog)s                  # Dry-run current directory\n"
        "  %(prog)s -a src/          # Autofix files in src/ directory\n"
        "  %(prog)s --autofix file.py other.py  # Autofix specific files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Modify files in-place (default: dry-run only)",
    )
    args = parser.parse_args()
    python_files = find_python_files(args.paths)
    if not python_files:
        print("No Python files found.")
        sys.exit(1)
    print(f"Found {len(python_files)} Python file(s). Processing in parallel...")
    file_args = [(f, args.autofix) for f in python_files]
    with Pool() as pool:
        results = pool.map(process_file, file_args)
    report_stats(results, args.autofix)
    errors = [r for r in results if r.status == "error"]
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    raise SystemExit(main())
