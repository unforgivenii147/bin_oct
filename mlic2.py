#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from collections import defaultdict
from functools import partial
from pathlib import Path

TEXT_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".csv",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".xml",
    ".svg",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".lua",
    ".r",
    ".swift",
    ".kt",
    ".scala",
    ".clj",
    ".groovy",
}
EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".flv",
    ".wmv",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}


def is_text_file(path: Path) -> bool:
    if path.suffix in EXCLUDED_EXTENSIONS:
        return False
    if path.suffix in TEXT_EXTENSIONS:
        return True
    if "." not in path.name:
        try:
            with open(path, "rb") as f:
                sample = f.read(1024)
                if not sample:
                    return True
                text_chars = sum(
                    1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13)
                )
                return text_chars / len(sample) > 0.8
        except OSError:
            return False
    return False


def read_file_content(path: Path) -> tuple[Path, list[str], str]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return path, lines, "".join(lines)
    except UnicodeDecodeError:
        try:
            with open(path, encoding="latin-1") as f:
                lines = f.readlines()
            return path, lines, "".join(lines)
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: cannot read {path}: {e}", file=sys.stderr)
            return path, [], ""
    except OSError as e:
        print(f"Warning: cannot read {path}: {e}", file=sys.stderr)
        return path, [], ""


def find_multiline_blocks(
    text: str, min_lines: int = 3
) -> dict[str, list[tuple[int, str]]]:
    lines = text.splitlines()
    if len(lines) < min_lines:
        return {}
    blocks = defaultdict(list)
    seen_blocks = set()
    for start in range(len(lines) - min_lines + 1):
        for end in range(start + min_lines, len(lines) + 1):
            block = "\n".join(lines[start:end])
            block_stripped = block.strip()
            if not block_stripped or len(block_stripped) < 10:
                continue
            if not any(c.isalnum() for c in block_stripped):
                continue
            block_key = block_stripped
            if block_key in seen_blocks:
                continue
            occurrences = []
            pos = text.find(block)
            while pos != -1:
                line_no = text.count("\n", 0, pos) + 1
                end_pos = pos + len(block)
                line_start = text.rfind("\n", 0, pos) + 1
                line_end = text.find("\n", end_pos)
                if line_end == -1:
                    line_end = len(text)
                context = text[line_start:line_end]
                occurrences.append((line_no, context.strip()))
                pos = text.find(block, end_pos)
            if len(occurrences) >= 2:
                blocks[block_key] = occurrences
                seen_blocks.add(block_key)
            if len(block_key) > 5000:
                break
    return dict(blocks)


def scan_file(path: Path, min_lines: int = 3) -> dict[str, list[tuple[Path, int, str]]]:
    if not is_text_file(path):
        return {}
    path, _lines, text = read_file_content(path)
    if not text:
        return {}
    blocks = find_multiline_blocks(text, min_lines)
    result = {}
    for block, occurrences in blocks.items():
        result[block] = [(path, line_no, context) for line_no, context in occurrences]
    return result


def collect_multiline_repeats(
    root: Path, min_lines: int = 3, num_workers: int | None = None
) -> dict[str, list[tuple[Path, int, str]]]:
    if num_workers is None:
        num_workers = mp.cpu_count()
    text_files = []
    for path in root.rglob("*"):
        if (
            path.is_file()
            and is_text_file(path)
            and not path.is_symlink()
            and ".git" not in path.parts
        ):
            text_files.append(path)
    if not text_files:
        return {}
    print(f"Scanning {len(text_files)} text files using {num_workers} workers...")
    with mp.Pool(processes=num_workers) as pool:
        scan_func = partial(scan_file, min_lines=min_lines)
        results = pool.map(scan_func, text_files)
    combined = defaultdict(list)
    for result in results:
        for block, occurrences in result.items():
            combined[block].extend(occurrences)
    filtered = {}
    for block, occurrences in combined.items():
        file_occurrences = defaultdict(list)
        for path, line_no, context in occurrences:
            file_occurrences[path].append((line_no, context))
        if len(file_occurrences) >= 2 or any(
            len(occ) >= 2 for occ in file_occurrences.values()
        ):
            filtered[block] = occurrences
    return filtered


def report(repeated: dict[str, list[tuple[Path, int, str]]]) -> None:
    if not repeated:
        print("No repeated multiline blocks found.")
        return
    print(f"Found {len(repeated)} repeated multiline blocks:")
    for i, (block, occurrences) in enumerate(repeated.items(), 1):
        print(f"\n--- Block {i} ---")
        print(block[:200] + ("..." if len(block) > 200 else ""))
        print(f"Found in {len(occurrences)} locations:")
        for path, lineno, context in occurrences:
            print(f"  {path}:{lineno} -> {context[:100]}...")
        print("-" * 40)


def save_to_file(
    repeated: dict[str, list[tuple[Path, int, str]]], output_file: Path
) -> None:
    if not repeated:
        return
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("REPEATED MULTILINE BLOCKS FOUND\n")
            f.write(f"{'=' * 40}\n\n")
            for block_num, (block, occurrences) in enumerate(repeated.items(), 1):
                f.write(f"BLOCK #{block_num}\n")
                f.write(f"{'-' * 40}\n")
                f.write(block)
                f.write("\n\nLOCATIONS:\n")
                for path, lineno, context in occurrences:
                    f.write(f"  {path}:{lineno}\n")
                    f.write(f"    -> {context}\n")
                f.write(f"\n{'=' * 40}\n\n")
        print(f"Results saved to {output_file}")
    except OSError as e:
        print(f"Error writing to {output_file}: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find repeated multiline blocks in text files",
        epilog="Example: python script.py -m 4 -o output.txt",
    )
    parser.add_argument(
        "-m",
        "--min-lines",
        type=int,
        default=3,
        help="Minimum lines for a block to be considered (default: 3)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="output.txt",
        help="Output file for findings (default: output.txt)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=str,
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()
    root = Path(args.directory)
    if not root.exists():
        print(f"Error: Directory {root} does not exist", file=sys.stderr)
        sys.exit(1)
    print(f"Scanning directory: {root}")
    print(f"Minimum block size: {args.min_lines} lines")
    print(f"Using {args.workers or mp.cpu_count()} workers")
    print()
    repeated = collect_multiline_repeats(root, args.min_lines, args.workers)
    output_path = Path(args.output)
    save_to_file(repeated, output_path)
    report(repeated)


if __name__ == "__main__":
    raise SystemExit(main())
