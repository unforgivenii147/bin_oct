#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import ast
import sys
import time
from collections import defaultdict
from pathlib import Path

from joblib import Parallel, delayed


def is_text_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" not in chunk
    except OSError:
        return False


def extract_blocks_from_file(
    path: Path, min_lines: int = 2
) -> list[tuple[str, int, list[str]]]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Warning: cannot read {path}: {e}", file=sys.stderr)
        return []
    blocks = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("#!"):
            i += 1
            continue
        block_start = i
        block_lines = []
        block_stripped = []
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("#!"):
                break
            block_lines.append(lines[i].rstrip("\n\r"))
            block_stripped.append(stripped)
            i += 1
        if len(block_stripped) >= min_lines:
            block_text = "\n".join(block_stripped)
            blocks.append((block_text, block_start + 1, block_lines))
    return blocks


def collect_blocks_parallel(
    root: Path, min_lines: int = 2, n_jobs: int = 8
) -> dict[str, list[tuple[Path, int, list[str]]]]:
    all_files = [
        path for path in root.rglob("*") if path.is_file() and is_text_file(path)
    ]
    total_files = len(all_files)
    if not total_files:
        return defaultdict(list)
    print(f"Scanning {total_files} files...", file=sys.stderr)
    batch_size = 100
    blocks_dict: dict[str, list[tuple[Path, int, list[str]]]] = defaultdict(list)
    for batch_start in range(0, total_files, batch_size):
        batch_end = min(batch_start + batch_size, total_files)
        batch_files = all_files[batch_start:batch_end]
        results = Parallel(n_jobs=n_jobs, prefer="threads", verbose=0)(
            delayed(extract_blocks_from_file)(path, min_lines) for path in batch_files
        )
        for path, blocks in zip(batch_files, results, strict=False):
            for block_text, start_lineno, original_lines in blocks:
                blocks_dict[block_text].append((path, start_lineno, original_lines))
    return blocks_dict


def find_repeated_blocks(
    blocks: dict[str, list[tuple[Path, int, list[str]]]],
) -> dict[str, list[tuple[Path, int, list[str]]]]:
    return {block: occ for block, occ in blocks.items() if len(occ) >= 2}


def report(repeated: dict[str, list[tuple[Path, int, list[str]]]], root: Path) -> None:
    if not repeated:
        print("No repeated multi-line blocks found.")
        return
    print(f"Found {len(repeated)} repeated multi-line block(s):")
    for i, (block_text, occurrences) in enumerate(repeated.items(), 1):
        line_count = block_text.count("\n") + 1
        unique_files = {occ[0] for occ in occurrences}
        print(f"""
--- Block {i} ({len(occurrences)} occurrences in {len(unique_files)} files, {line_count} lines) ---""")
        for line in block_text.split("\n"):
            print(f"  {line}")
        print("  Found in:")
        for path, lineno, _ in occurrences:
            try:
                rel_path = path.relative_to(root)
            except ValueError:
                rel_path = path
            print(f"    {rel_path}:{lineno}")


def process_file_removal(
    path: Path, removals: list[tuple[int, list[str]]], root: Path
) -> tuple[Path, int, bool]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            original_lines = f.readlines()
    except OSError as e:
        print(f"Warning: cannot read {path}: {e}", file=sys.stderr)
        return path, 0, False
    lines_to_remove: set[int] = set()
    for start_lineno, block_lines in removals:
        for offset in range(len(block_lines)):
            lines_to_remove.add(start_lineno + offset - 1)
    if any(idx >= len(original_lines) for idx in lines_to_remove):
        print(f"Warning: Invalid line numbers in {path}", file=sys.stderr)
        return path, 0, False
    new_lines = [
        line for idx, line in enumerate(original_lines) if idx not in lines_to_remove
    ]
    removed_count = len(original_lines) - len(new_lines)
    if removed_count == 0:
        return path, 0, False
    if path.suffix == ".py":
        try:
            ast.parse("".join(new_lines))
        except SyntaxError as e:
            try:
                rel_path = path.relative_to(root)
            except ValueError:
                rel_path = path
            print(
                f"Warning: Removing blocks from {rel_path} would create invalid Python: {e}",
                file=sys.stderr,
            )
            return path, 0, False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return path, removed_count, True
    except OSError as e:
        print(f"Error: cannot write {path}: {e}", file=sys.stderr)
        return path, 0, False


def remove_repeated_blocks(
    repeated: dict[str, list[tuple[Path, int, list[str]]]], root: Path, n_jobs: int = 8
) -> None:
    file_removals: dict[Path, list[tuple[int, list[str]]]] = defaultdict(list)
    for occurrences in repeated.values():
        for path, start_lineno, original_lines in occurrences:
            file_removals[path].append((start_lineno, original_lines))
    if not file_removals:
        print("No files to modify.")
        return
    print(f"Removing blocks from {len(file_removals)} files...", file=sys.stderr)
    results = Parallel(n_jobs=n_jobs, prefer="threads", verbose=0)(
        delayed(process_file_removal)(path, removals, root)
        for path, removals in file_removals.items()
    )
    removed_total = 0
    files_changed = 0
    for path, file_removed, success in results:
        if success and file_removed > 0:
            removed_total += file_removed
            files_changed += 1
            try:
                rel_path = path.relative_to(root)
            except ValueError:
                rel_path = path
            print(f"Removed {file_removed} line(s) from {rel_path}")
    if files_changed > 0:
        print(
            f"\nDone. Removed {removed_total} repeated line(s) from {files_changed} file(s)."
        )
    else:
        print("No files were modified.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-r",
        "--remove",
        action="store_true",
        help="Remove found repeated multi-line blocks from files",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=2,
        help="Minimum consecutive lines to consider a block (default: 2)",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=8, help="Number of parallel jobs (default: 8)"
    )
    args = parser.parse_args()
    root = Path.cwd()
    start_time = time.time()
    blocks = collect_blocks_parallel(root, args.min_lines, args.jobs)
    scan_time = time.time() - start_time
    print(
        f"Scan completed in {scan_time:.2f}s, found {len(blocks)} unique blocks",
        file=sys.stderr,
    )
    repeated = find_repeated_blocks(blocks)
    if args.remove:
        if not repeated:
            print("No repeated multi-line blocks to remove.")
        else:
            print(f"Found {len(repeated)} repeated blocks to remove")
            remove_repeated_blocks(repeated, root, args.jobs)
    else:
        report(repeated, root)


if __name__ == "__main__":
    raise SystemExit(main())
