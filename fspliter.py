#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that splits text files into parts of a specified character range.

The script should:
- Accept input files and/or directories via positional CLI arguments (default: current directory).
- Support options: -o/--output (default: split_output), --no-recursive, --min-chars (default 4900), --max-chars (default 4990).
- Recursively find text files by extension (a predefined set) or files with no extension.
- Split each file's content into parts between min_chars and max_chars, preferring sentence boundaries (".!? "), then whitespace, else hard cut at max_chars.
- Use multiprocessing.Pool with exactly 8 workers via apply_async to process files in parallel.
- Use loguru for logging.
- Use pathlib for all path handling.
- Include complete type annotations and docstrings for all functions, classes, and module-level constants.
- Handle UnicodeDecodeError by falling back to latin-1.
- Write each part to the output directory as {stem}_{i:03d}{suffix}.
- Log a summary of processed files and total parts.
"""

import argparse
import re
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from loguru import logger

DEFAULT_MIN_CHARS: Final[int] = 4900
DEFAULT_MAX_CHARS: Final[int] = 4990
POOL_SIZE: Final[int] = 8

TEXT_EXTENSIONS: Final[set[str]] = {
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".css",
    ".yml",
    ".yaml",
    ".cfg",
    ".ini",
}

SENTENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[.!?]\s+")
WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")


def find_text_files(input_paths: list[Path], recursive: bool = True) -> list[Path]:
    """Find all text files under the given paths.

    Args:
        input_paths: Files and/or directories to search.
        recursive: Whether to search directories recursively.

    Returns:
        A de-duplicated list of text file paths.
    """
    text_files: list[Path] = []
    for path in input_paths:
        if not path.exists():
            logger.warning(f"Path does not exist: {path}")
            continue
        if path.is_file():
            if path.suffix.lower() in TEXT_EXTENSIONS or path.suffix.lower() == "":
                text_files.append(path)
            else:
                logger.warning(f"Skipping non-text file: {path}")
        elif path.is_dir():
            if recursive:
                for ext in TEXT_EXTENSIONS:
                    text_files.extend(path.rglob(f"*{ext}"))
                text_files.extend(
                    [f for f in path.rglob("*") if f.is_file() and f.suffix == ""]
                )
            else:
                for ext in TEXT_EXTENSIONS:
                    text_files.extend(path.glob(f"*{ext}"))
                text_files.extend(
                    [f for f in path.glob("*") if f.is_file() and f.suffix == ""]
                )
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in text_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files


def find_split_point(text: str, start_pos: int, min_chars: int, max_chars: int) -> int:
    """Determine the best position to split text between min_chars and max_chars.

    Prefers splitting after a sentence boundary, then after whitespace,
    otherwise hard-cuts at max_chars.

    Args:
        text: The full text to split.
        start_pos: Index in text where the current part begins.
        min_chars: Minimum characters per part.
        max_chars: Maximum characters per part.

    Returns:
        The index at which to split.
    """
    end_pos = start_pos + max_chars
    if end_pos >= len(text):
        return len(text)
    search_start = start_pos + min_chars
    search_end = min(end_pos, len(text))
    search_text = text[search_start:search_end]
    matches = list(SENTENCE_PATTERN.finditer(search_text))
    if matches:
        last_match = matches[-1]
        split_point = search_start + last_match.end()
        return split_point
    matches = list(WORD_PATTERN.finditer(search_text))
    if matches:
        last_match = matches[-1]
        split_point = search_start + last_match.end()
        return split_point
    return end_pos


def split_text(text: str, min_chars: int, max_chars: int) -> list[str]:
    """Split text into parts between min_chars and max_chars.

    Args:
        text: The text to split.
        min_chars: Minimum characters per part.
        max_chars: Maximum characters per part.

    Returns:
        A list of text parts.
    """
    parts: list[str] = []
    current_pos = 0
    while current_pos < len(text):
        split_point = find_split_point(text, current_pos, min_chars, max_chars)
        part = text[current_pos:split_point]
        part = part.rstrip()
        if part:
            parts.append(part)
        current_pos = split_point
    return parts


def process_file(
    input_file: Path, output_dir: Path, min_chars: int, max_chars: int
) -> tuple[Path, int]:
    """Split a single file into parts and write them to the output directory.

    Args:
        input_file: Path to the input file.
        output_dir: Directory where split parts will be written.
        min_chars: Minimum characters per part.
        max_chars: Maximum characters per part.

    Returns:
        A tuple of (input_file, number_of_parts_written).
    """
    try:
        try:
            with open(input_file, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(input_file, encoding="latin-1") as f:
                content = f.read()
        if not content.strip():
            print(f"Skipping empty file: {input_file}")
            return (input_file, 0)
        parts = split_text(content, min_chars, max_chars)
        if not parts:
            print(f"No parts generated for: {input_file}")
            return (input_file, 0)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = input_file.stem
        suffix = input_file.suffix
        for i, part in enumerate(parts, 1):
            output_file = output_dir / f"{stem}_{i:03d}{suffix}"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(part)
        print(f"Split {input_file.name} into {len(parts)} parts")
        return (input_file, len(parts))
    except Exception as e:
        logger.error(f"Error processing {input_file}: {e}")
        return (input_file, 0)


def process_file_wrapper(
    args: tuple[Path, Path, int, int],
) -> tuple[Path, int]:
    """Unpack arguments and call process_file.

    Args:
        args: Tuple of (input_file, output_dir, min_chars, max_chars).

    Returns:
        A tuple of (input_file, number_of_parts_written).
    """
    return process_file(*args)


def main() -> int:
    """Entry point for the text file splitter CLI.

    Returns:
        Exit code (0 on success).
    """
    parser = argparse.ArgumentParser(
        description="Split text files into parts of 4900-4990 characters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s file1.txt file2.txt -o output/
  %(prog)s dir1/ dir2/ -o output/
  %(prog)s -o output/  (process all files in current directory)
  %(prog)s *.txt -o output/
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Input files and/or directories to process. If not provided, processes current directory recursively.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("split_output"),
        help="Output directory for split files (default: split_output)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not search directories recursively",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_CHARS,
        help=f"Minimum characters per part (default: {DEFAULT_MIN_CHARS})",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"Maximum characters per part (default: {DEFAULT_MAX_CHARS})",
    )
    args = parser.parse_args()

    if args.inputs:
        input_paths: list[Path] = [Path(p) for p in args.inputs]
    else:
        input_paths = [Path(".")]

    text_files: list[Path] = find_text_files(
        input_paths, recursive=not args.no_recursive
    )
    if not text_files:
        logger.error("No text files found to process")
        return 1

    print(f"Found {len(text_files)} file(s) to process")
    print(f"Character limits: {args.min_chars}-{args.max_chars} per part")

    process_args: list[tuple[Path, Path, int, int]] = [
        (path, args.output, args.min_chars, args.max_chars) for path in text_files
    ]

    total_parts: int = 0
    processed_files: int = 0

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(process_file_wrapper, (arg,)) for arg in process_args
        ]
        for async_result in async_results:
            try:
                _result_file, num_parts = async_result.get()
                total_parts += num_parts
                processed_files += 1
            except Exception as e:
                logger.error(f"Failed to process a file: {e}")

    print(
        f"Processing complete: {processed_files} files split into {total_parts} parts"
    )
    print(f"Output directory: {args.output.absolute()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
