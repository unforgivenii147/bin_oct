#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import sys
from collections import defaultdict
from pathlib import Path
from typing import dict, list, set, tuple

MIN_LINES = 3
MIN_CHARS = 100


def find_multiline_strings(
    path: Path, min_lines: int = 2, min_chars: int = 10
) -> dict[str, list[tuple[int, int]]]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return {}
    strings = defaultdict(list)
    i = 0
    while i < len(lines):
        if lines[i].strip():
            start = i
            string_lines = [lines[i]]
            i += 1
            while i < len(lines) and lines[i].strip():
                string_lines.append(lines[i])
                i += 1
            end = i - 1
            full_string = "".join(string_lines)
            if len(string_lines) >= min_lines and len(full_string.strip()) >= min_chars:
                normalized = normalize_string(full_string)
                strings[normalized].append((start, end))
        else:
            i += 1
    return strings


def normalize_string(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines())


def validate_python_syntax(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return (False, f"Syntax error at line {e.lineno}, column {e.offset}: {e.msg}")


def find_files(directory: Path, extensions: set[str] | None = None) -> list[Path]:
    if extensions is None:
        extensions = {
            ".txt",
            ".md",
            ".py",
            ".js",
            ".html",
            ".css",
            ".xml",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".log",
            ".ini",
            ".cfg",
            ".conf",
            ".sh",
            ".bat",
            ".ps1",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".rb",
            ".php",
            ".sql",
        }
    files = []
    try:
        for item in directory.rglob("*"):
            if item.is_file() and item.suffix.lower() in extensions:
                files.append(item)
    except PermissionError:
        print(f"Permission denied accessing {directory}", file=sys.stderr)
    return files


def process_file(
    args: tuple[Path, int, int],
) -> tuple[Path, dict[str, list[tuple[int, int]]]]:
    path, min_lines, min_chars = args
    strings = find_multiline_strings(path, min_lines, min_chars)
    return path, strings


def find_repeated_strings(
    directory: Path,
    min_lines: int = 2,
    min_chars: int = 10,
    max_workers: int | None = None,
    half: bool = False,
) -> dict[str, list[tuple[Path, list[tuple[int, int]]]]]:
    files = find_files(directory)
    if not files:
        print("No text files found in directory", file=sys.stderr)
        return {}
    print(f"Found {len(files)} files to process...")
    all_strings = defaultdict(list)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        args = [(f, min_lines, min_chars) for f in files]
        futures = {executor.submit(process_file, arg): arg[0] for arg in args}
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                path, strings = future.result()
                for norm_str, positions in strings.items():
                    all_strings[norm_str].append((path, positions))
            except Exception as e:
                print(f"Error processing {path}: {e}", file=sys.stderr)
    repeated = {k: v for k, v in all_strings.items() if len(v) > 1}
    if half:
        total_files = len(files)
        half_threshold = total_files / 2
        repeated = {k: v for k, v in repeated.items() if len(v) >= half_threshold}
        if repeated:
            print(
                f"Filtered to strings appearing in at least 50% of files ({int(half_threshold)} files)"
            )
        else:
            print("No strings found that appear in at least 50% of files")
    return repeated


def remove_strings_from_files(
    repeated_strings: dict[str, list[tuple[Path, list[tuple[int, int]]]]],
    string_numbers: list[int] | None = None,
    validate: bool = True,
):
    files_to_modify = defaultdict(set)
    if string_numbers:
        selected_strings = {}
        for i, (norm_str, occurrences) in enumerate(repeated_strings.items(), 1):
            if i in string_numbers:
                selected_strings[norm_str] = occurrences
    else:
        selected_strings = repeated_strings
    for norm_str, occurrences in selected_strings.items():
        for path, positions in occurrences:
            files_to_modify[path].update(positions)
    skipped_files = []
    modified_files = []
    for path, positions in files_to_modify.items():
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                original_content = f.read()
                lines = f.seek(0) or original_content.splitlines(True)
            lines = original_content.splitlines(True)
            sorted_positions = sorted(positions, key=lambda x: x[0], reverse=True)
            for start, end in sorted_positions:
                del lines[start : end + 1]
            new_content = "".join(lines)
            if path.suffix.lower() == ".py" and validate:
                is_valid, error_msg = validate_python_syntax(new_content)
                if not is_valid:
                    print(
                        f"SKIPPED: {path} - Syntax validation failed: {error_msg}",
                        file=sys.stderr,
                    )
                    skipped_files.append((path, error_msg))
                    continue
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Modified: {path} - Removed {len(positions)} string(s)")
            modified_files.append(path)
        except Exception as e:
            print(f"Error modifying {path}: {e}", file=sys.stderr)
    if skipped_files:
        print(f"\nSkipped {len(skipped_files)} file(s) due to syntax errors:")
        for path, error in skipped_files:
            print(f"  - {path}: {error}")
    return modified_files, skipped_files


def save_strings_to_file(
    repeated_strings: dict[str, list[tuple[Path, list[tuple[int, int]]]]],
    output_file: Path,
):
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("Repeated Multiline Strings Report\n")
            f.write("=" * 40 + "\n\n")
            for i, (norm_str, occurrences) in enumerate(repeated_strings.items(), 1):
                f.write(f"String #{i} (found {len(occurrences)} times):\n")
                f.write("-" * 30 + "\n")
                f.write(norm_str)
                f.write("\n\n")
        print(f"Report saved to {output_file}")
    except Exception as e:
        print(f"Error saving report: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Find repeated multiline strings in text files recursively"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to search (default: current directory)",
    )
    parser.add_argument(
        "-r",
        "--remove",
        nargs="*",
        type=int,
        help="Remove found repeated strings. Optionally specify string numbers (e.g., -r 2 4 to remove strings #2 and #4)",
    )
    parser.add_argument(
        "-H",
        "--half",
        action="store_true",
        help="Only show strings found in at least 50 percent of files",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Python syntax validation (use with caution)",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=MIN_LINES,
        help=f"Minimum number of lines for a multiline string (default: {MIN_LINES})",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=MIN_CHARS,
        help=f"Minimum number of characters for a multiline string (default: {MIN_CHARS})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        help="File extensions to process (e.g., .txt .md .py)",
    )
    args = parser.parse_args()
    directory = Path(args.directory)
    if not directory.exists():
        print(f"Directory {directory} does not exist", file=sys.stderr)
        sys.exit(1)
    print(f"Searching for repeated multiline strings in {directory}...")
    if args.extensions:
        extensions = set(args.extensions)
        global find_files
        original_find_files = find_files

        def find_files_with_ext(directory, _=None):
            return original_find_files(directory, extensions)

        find_files = find_files_with_ext
    if args.half:
        print(
            "Filtering: Only strings appearing in at least 50% of files will be shown"
        )
    repeated = find_repeated_strings(
        directory,
        min_lines=args.min_lines,
        min_chars=args.min_chars,
        max_workers=args.workers,
        half=args.half,
    )
    output_file = Path.cwd() / "lic.txt"
    save_strings_to_file(repeated, output_file)
    if not repeated:
        print("No repeated multiline strings found.")
        return
    print(f"\nFound {len(repeated)} repeated multiline strings:")
    for i, (norm_str, occurrences) in enumerate(repeated.items(), 1):
        preview = norm_str[:100] + "..." if len(norm_str) > 100 else norm_str
        preview = preview.replace("\n", "\\n")
        print(f"\n{i}. Found in {len(occurrences)} files:")
        print(f"   Preview: {preview}")
        for path, positions in occurrences:
            print(f"   - {path}")
            for start, end in positions:
                print(f"     Lines {start + 1}-{end + 1}")
    if args.remove is not None:
        string_numbers = args.remove if args.remove else None
        if string_numbers:
            max_num = len(repeated)
            invalid_nums = [n for n in string_numbers if n < 1 or n > max_num]
            if invalid_nums:
                print(
                    f"\nError: Invalid string numbers: {invalid_nums}. Valid range: 1-{max_num}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"\nRemoving strings: {string_numbers}...")
        else:
            print("\nRemoving all repeated strings from files...")
        validate = not args.no_validate
        if validate:
            print(
                "Python syntax validation enabled. Use --no-validate to skip validation."
            )
        modified_files, skipped_files = remove_strings_from_files(
            repeated, string_numbers, validate
        )
        if modified_files:
            print(f"\nSuccessfully modified {len(modified_files)} file(s).")
        if skipped_files:
            print(f"Skipped {len(skipped_files)} file(s) due to syntax errors.")
            print(
                "These files were NOT modified. Review the strings manually or use --no-validate."
            )


if __name__ == "__main__":
    raise SystemExit(main())
