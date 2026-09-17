#!/data/data/com.termux/files/home/.local/bin/python
"""
Convert non-UTF8 text files to UTF-8 in place. Detects each file's encoding with
chardet, skips binary/unsupported files via ``dh.is_binary``, and rewrites
non-UTF8 sources as UTF-8 with ``errors="replace"``. Files are processed with a
fixed multiprocessing.Pool of 8 workers. Logging via loguru.
"""

import argparse
from collections.abc import Generator
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

import chardet  # type: ignore[import-untyped]
from dh import get_nobinary, is_binary  # type: ignore[import-untyped]
from loguru import logger

MAX_WORKERS: Final[int] = 8
SAMPLE_SIZE: Final[int] = 100_000

ConvertResult = tuple[Path, bool, str]


def detect_encoding(file_path: Path) -> str:
    """
    Detect the encoding of ``file_path`` using chardet on a leading sample.

    Args:
        file_path: File whose encoding should be detected.

    Returns:
        The detected encoding name, defaulting to ``"utf-8"`` on failure or
        when chardet returns no encoding.
    """
    try:
        with file_path.open("rb") as f:
            raw_data: bytes = f.read(SAMPLE_SIZE)
        result: dict[str, str | float | None] = chardet.detect(raw_data)
        encoding: str | float | None = result.get("encoding")
        if isinstance(encoding, str) and encoding:
            return encoding
        return "utf-8"
    except Exception:
        return "utf-8"


def convert_file(file_path: Path) -> ConvertResult:
    """
    Convert a single file to UTF-8 in place if it is not already UTF-8.

    Args:
        file_path: Path to the file to process.

    Returns:
        A tuple ``(path, success, message)`` where ``success`` is ``True`` for
        converted or already-UTF8 files, ``False`` for skipped or errored files.
    """
    try:
        if is_binary(file_path):
            return file_path, False, "Skipped (binary/unsupported)"

        encoding: str = detect_encoding(file_path)
        if encoding.lower() == "utf-8":
            return file_path, True, "Already UTF8"

        with file_path.open("r", encoding=encoding, errors="replace") as f:
            content: str = f.read()
        with file_path.open("w", encoding="utf-8") as f:
            f.write(content)

        return file_path, True, f"Converted from {encoding}"
    except Exception as exc:
        return file_path, False, f"Error: {exc!s}"


def collect_files(paths: list[str]) -> Generator[Path, None, None]:
    """
    Yield resolved file paths from the given files and directories.

    Args:
        paths: File or directory path strings.

    Yields:
        Resolved ``Path`` objects. Directories are traversed recursively.
        Non-existent paths are logged as warnings and skipped.
    """
    for path_str in paths:
        path: Path = Path(path_str).resolve()
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    yield child
        else:
            logger.warning(f"⚠ {path} not found")


def main() -> int:
    """Parse CLI arguments and convert files in parallel."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Convert non-UTF8 files to UTF8 encoding (in-place)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python script.py                    # Process current directory\n"
            "  python script.py ./src ./docs       # Process specific directories\n"
            "  python script.py file.txt dir/      # Process file and directory"
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for each file",
    )
    args: argparse.Namespace = parser.parse_args()

    input_paths: list[str] = list(args.paths) if args.paths else ["."]
    cwd: Path = Path.cwd()

    # Honor explicit CLI paths when provided, otherwise scan CWD via dh.
    if args.paths:
        files: list[Path] = list(collect_files(input_paths))
    else:
        files = list(get_nobinary(cwd))

    if not files:
        print("No files to process.")
        return 0

    print(f"Processing {len(files)} file(s) with {MAX_WORKERS} worker(s)...\n")

    converted: int = 0
    skipped: int = 0
    errors: int = 0

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[ConvertResult]] = [
            pool.apply_async(convert_file, (f,)) for f in files
        ]
        for async_res in async_results:
            file_path, success, message = async_res.get()
            if args.verbose:
                status: str = "✓" if success else "✗"
                try:
                    rel: Path = file_path.relative_to(cwd)
                except ValueError:
                    rel = file_path
                print(f"{status} {rel} - {message}")
            if success:
                if "Already UTF8" in message or "Skipped" in message:
                    skipped += 1
                else:
                    converted += 1
            else:
                errors += 1

    print("=" * 40)
    print("Summary:")
    print(f"  Converted: {converted}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print("=" * 40)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
