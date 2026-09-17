#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that recursively extracts shell function definitions from Bash scripts
(.sh files and extensionless files with shell shebangs), skipping non-shell source files, and
writes each function into its own file under an output directory, using multiprocessing.Pool
with a fixed pool of 8 workers, pathlib for all path handling, and loguru for logging.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Final

from fastwalk import walk_files
from loguru import logger

EXCLUDED: Final[set[str]] = {
    ".py",
    ".h",
    ".c",
    ".js",
    ".ts",
    ".hpp",
    ".cpp",
    ".pyx",
    ".jsx",
    ".lua",
    ".tsx",
    ".pl",
    ".am",
    ".pm",
    ".syntax",
}

IS_TERMUX: Final[bool] = "TERMUX_VERSION" in __import__(
    "os"
).environ or "com.termux" in __import__("os").environ.get("PREFIX", "")

POOL_WORKERS: Final[int] = 8

MAX_SCRIPT_SIZE_BYTES: Final[int] = 1_000_000

SHELL_PATTERNS: Final[tuple[str, ...]] = (
    "bash",
    "sh",
    "dash",
    "ksh",
    "zsh",
    "ash",
    "shell",
)

FUNCTION_START_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:function\s+)?(\w[\w\-]*)\s*(?:\(\))?\s*\{"
)

SAFE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w\-]")


def is_bash_script(path: Path) -> bool:
    """Return True if the given path appears to be a Bash/shell script.

    A file is considered a shell script if it ends with ``.sh`` or, for
    extensionless files under the size limit, its shebang line references a
    known shell interpreter. Binary files and non-files are rejected.
    """
    if path.suffix == ".sh":
        return True
    if not path.is_file():
        return False
    try:
        if path.stat().st_size > MAX_SCRIPT_SIZE_BYTES:
            return False
    except OSError:
        return False
    try:
        with open(path, "rb") as handle:
            first_bytes = handle.read(2)
            if b"\x00" in first_bytes:
                return False
            handle.seek(0)
            first_line = handle.readline().decode("utf-8", errors="ignore").strip()
            if first_line.startswith("#!"):
                shebang_lower = first_line.lower()
                if any(shell in shebang_lower for shell in SHELL_PATTERNS):
                    return True
    except (OSError, UnicodeDecodeError):
        return False
    return False


def find_sh_files(paths: list[Path], include_extensionless: bool = True) -> set[Path]:
    """Collect resolved paths of shell scripts from the given files and directories.

    Files are included directly if they are shell scripts. Directories are
    walked recursively via ``fastwalk.walk_files``. Files whose suffix appears
    in ``EXCLUDED`` are skipped, and when ``include_extensionless`` is False
    only ``.sh`` files are kept.
    """
    sh_files: set[Path] = set()
    for path in paths:
        if not path.exists():
            logger.warning("{} does not exist, skipping...", path)
            continue
        if path.is_file():
            if is_bash_script(path):
                sh_files.add(path.resolve())
        elif path.is_dir():
            for item in walk_files(path):
                item_path = Path(item)
                if item_path.suffix in EXCLUDED:
                    continue
                if not include_extensionless and item_path.suffix != ".sh":
                    continue
                if item_path.is_file() and is_bash_script(item_path):
                    sh_files.add(item_path.resolve())
        else:
            logger.warning("{} is not a file or directory, skipping...", path)
    return sh_files


def extract_functions_from_file(sh_file: Path) -> list[tuple[str, str, Path]]:
    """Extract top-level function definitions from a shell script file.

    Returns a list of ``(name, body, source_path)`` tuples, where ``body`` is
    the full text of the function including its header and matching closing
    brace. Functions whose closing brace cannot be matched are skipped with a
    warning.
    """
    try:
        with open(sh_file, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()
    except OSError as exc:
        logger.error("Error reading {}: {}", sh_file, exc)
        return []

    functions: list[tuple[str, str, Path]] = []
    lines = content.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        match = FUNCTION_START_PATTERN.match(line)
        if match:
            func_name = match.group(1)
            func_lines: list[str] = [line]
            brace_count = line.count("{") - line.count("}")
            inner = index + 1
            while inner < len(lines) and brace_count > 0:
                current_line = lines[inner]
                func_lines.append(current_line)
                brace_count += current_line.count("{") - current_line.count("}")
                inner += 1
            if brace_count == 0:
                function_content = "\n".join(func_lines)
                functions.append((func_name, function_content, sh_file))
            else:
                logger.warning(
                    "Could not find matching closing brace for function '{}' in {}",
                    func_name,
                    sh_file,
                )
            index = inner
        else:
            index += 1
    return functions


def process_file(
    sh_file: Path, output_dir: Path, use_extension: bool = True
) -> list[tuple[str, Path]]:
    """Extract functions from a single shell script and write each to its own file.

    Returns a list of ``(function_name, output_path)`` tuples for functions
    that were successfully written.
    """
    functions = extract_functions_from_file(sh_file)
    saved_functions: list[tuple[str, Path]] = []
    for func_name, func_content, source_file in functions:
        safe_func_name = SAFE_NAME_PATTERN.sub("_", func_name)
        try:
            rel_path = source_file.relative_to(Path.cwd())
        except ValueError:
            rel_path = source_file
        func_output_dir = output_dir / rel_path.parent
        if use_extension:
            output_file = func_output_dir / f"{safe_func_name}.sh"
        else:
            output_file = func_output_dir / safe_func_name
        func_output_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(output_file, "w", encoding="utf-8") as handle:
                handle.write(func_content)
                handle.write("\n")
            saved_functions.append((func_name, output_file))
        except OSError as exc:
            logger.error(
                "Error writing function '{}' to {}: {}", func_name, output_file, exc
            )
    return saved_functions


def _process_file_star(args: tuple[Path, Path, bool]) -> list[tuple[str, Path]]:
    """Adapter to unpack a tuple of arguments for ``process_file`` under Pool."""
    return process_file(*args)


def main() -> int:
    """Parse CLI arguments, discover shell scripts, and dispatch extraction work."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract functions from shell scripts (.sh and extensionless) recursively"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "\nExamples:\n"
            "  # Process all shell scripts in current directory recursively\n"
            "  %(prog)s\n"
            "  \n"
            "  # Process specific files and directories\n"
            "  %(prog)s script1.sh myscript dir1/ dir2/\n"
            "  \n"
            "  # Specify output directory\n"
            "  %(prog)s -o extracted_functions dir1/ dir2/\n"
            "  \n"
            "  # Only process .sh files (ignore extensionless scripts)\n"
            "  %(prog)s --sh-only\n"
            "  \n"
            "  # In Termux, this is automatically detected\n"
            "  %(prog)s ~/storage/shared/scripts/\n"
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "Files and/or directories to process. If none provided, processes all "
            "shell scripts in current directory recursively."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("extracted_functions"),
        help="Output directory for extracted functions (default: extracted_functions)",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Disable parallel processing (process sequentially)",
    )
    parser.add_argument(
        "--sh-only",
        action="store_true",
        help="Only process files with .sh extension (ignore extensionless scripts)",
    )
    parser.add_argument(
        "--no-extension",
        action="store_true",
        help="Output functions without .sh extension",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose output including skipped files",
    )
    args = parser.parse_args()

    if IS_TERMUX:
        print("Running in Termux environment (using {} workers)", POOL_WORKERS)

    if args.inputs:
        input_paths: list[Path] = args.inputs
    else:
        input_paths = [Path(".")]

    print("Searching for shell scripts...")
    include_extensionless = not args.sh_only
    sh_files = find_sh_files(input_paths, include_extensionless)

    if not sh_files:
        print("No shell scripts found to process.")
        if not args.sh_only:
            print("Tip: Use --sh-only to only process .sh files")
        return 0

    print("Found {} shell script(s) to process:", len(sh_files))
    if args.verbose:
        for path in sorted(sh_files):
            logger.debug("  - {}", path)

    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        logger.error(
            "Cannot create output directory '{}'. Check permissions.", args.output
        )
        return 1

    total_functions = 0
    use_extension = not args.no_extension

    if args.no_parallel or len(sh_files) == 1:
        print("Processing files sequentially...")
        for sh_file in sorted(sh_files):
            saved = process_file(sh_file, args.output, use_extension)
            total_functions += len(saved)
            if args.verbose or saved:
                print("  {}: extracted {} function(s)", sh_file, len(saved))
    else:
        print("Processing files in parallel with {} workers...", POOL_WORKERS)
        tasks: list[tuple[Path, Path, bool]] = [
            (sh_file, args.output, use_extension) for sh_file in sh_files
        ]
        with Pool(processes=POOL_WORKERS) as pool:
            async_results = [
                (sh_file, pool.apply_async(_process_file_star, (task,)))
                for sh_file, task in zip(sh_files, tasks)
            ]
            for sh_file, async_result in async_results:
                try:
                    saved = async_result.get()
                    total_functions += len(saved)
                    if args.verbose or saved:
                        print("  {}: extracted {} function(s)", sh_file, len(saved))
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error processing {}: {}", sh_file, exc)

    print(
        "\nDone! Extracted {} function(s) to '{}'",
        total_functions,
        args.output.absolute(),
    )

    if IS_TERMUX:
        with contextlib.suppress(BaseException):
            args.output.chmod(args.output.stat().st_mode | 0o755)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user. Exiting...")
        sys.exit(1)
