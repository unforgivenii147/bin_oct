#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that applies all available lib2to3 fixes to Python files.

The script should:
- Accept one or more file or directory paths as positional CLI arguments.
- Support a --dry-run/-d flag to preview changes without writing them.
- Support an --extensions/-e flag to override the default ".py" extension filter.
- Recursively discover matching files under directories using pathlib.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers (no worker-count CLI flags).
- Use a custom RefactoringTool subclass that captures output and errors.
- Log all progress, results, and summaries with loguru instead of print(or stdlib logging.)
- Provide strict type annotations throughout and pass a strict type checker.
- Exit with status 0 on full success, 1 if any file fails or no files are found.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from lib2to3.refactor import RefactoringTool, get_fixers_from_package
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from loguru import logger

# Module-level constants
WORKER_COUNT: int = 8
DEFAULT_EXTENSIONS: list[str] = [".py"]
MAX_DIFF_LINES: int = 5
MAX_DRY_RUN_DIFF_LINES: int = 20
MAX_PREVIEW_CHARS: int = 80
MAX_CHANGE_PREVIEW_CHARS: int = 50

FALLBACK_FIXERS: list[str] = [
    "lib2to3.fixes.fix_apply",
    "lib2to3.fixes.fix_asserts",
    "lib2to3.fixes.fix_basestring",
    "lib2to3.fixes.fix_buffer",
    "lib2to3.fixes.fix_dict",
    "lib2to3.fixes.fix_except",
    "lib2to3.fixes.fix_exec",
    "lib2to3.fixes.fix_execfile",
    "lib2to3.fixes.fix_exitfunc",
    "lib2to3.fixes.fix_filter",
    "lib2to3.fixes.fix_funcattrs",
    "lib2to3.fixes.fix_future",
    "lib2to3.fixes.fix_getcwdu",
    "lib2to3.fixes.fix_has_key",
    "lib2to3.fixes.fix_idioms",
    "lib2to3.fixes.fix_import",
    "lib2to3.fixes.fix_imports",
    "lib2to3.fixes.fix_imports2",
    "lib2to3.fixes.fix_input",
    "lib2to3.fixes.fix_itertools",
    "lib2to3.fixes.fix_itertools_imports",
    "lib2to3.fixes.fix_long",
    "lib2to3.fixes.fix_map",
    "lib2to3.fixes.fix_metaclass",
    "lib2to3.fixes.fix_methodattrs",
    "lib2to3.fixes.fix_ne",
    "lib2to3.fixes.fix_next",
    "lib2to3.fixes.fix_nonzero",
    "lib2to3.fixes.fix_numliterals",
    "lib2to3.fixes.fix_operator",
    "lib2to3.fixes.fix_paren",
    "lib2to3.fixes.fix_print",
    "lib2to3.fixes.fix_raise",
    "lib2to3.fixes.fix_raw_input",
    "lib2to3.fixes.fix_reduce",
    "lib2to3.fixes.fix_reload",
    "lib2to3.fixes.fix_renames",
    "lib2to3.fixes.fix_repr",
    "lib2to3.fixes.fix_set_literal",
    "lib2to3.fixes.fix_standarderror",
    "lib2to3.fixes.fix_sys_exc",
    "lib2to3.fixes.fix_throw",
    "lib2to3.fixes.fix_tuple_params",
    "lib2to3.fixes.fix_types",
    "lib2to3.fixes.fix_unicode",
    "lib2to3.fixes.fix_urllib",
    "lib2to3.fixes.fix_ws_comma",
    "lib2to3.fixes.fix_xrange",
    "lib2to3.fixes.fix_xreadlines",
    "lib2to3.fixes.fix_zip",
]


class CustomRefactoringTool(RefactoringTool):
    """A RefactoringTool that captures log output and errors instead of printing them."""

    output_lines: list[str]
    errors: list[str]

    def __init__(
        self,
        fixers: Iterable[str],
        explicit: Iterable[str] | None = None,
        append: Iterable[str] | None = None,
    ) -> None:
        """Initialize the tool with a list of fixers and capture buffers.

        Args:
            fixers: The fixer names to load.
            explicit: Explicit fixers to always run.
            append: Additional fixers appended to the defaults.
        """
        self.output_lines = []
        self.errors = []
        super().__init__(fixers, explicit, append)

    def log_error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Capture an error message from the refactoring tool."""
        self.errors.append(msg % args if args else msg)

    def write(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Capture a write call from the refactoring tool."""
        if args:
            msg = msg % args
        self.output_lines.append(msg)


def get_all_fixers() -> list[str]:
    """Return the list of all available lib2to3 fixers, with a static fallback."""
    try:
        fixers = get_fixers_from_package("lib2to3.fixes")
        return list(fixers)
    except ImportError as e:
        logger.warning(f"Error loading fixers: {e}")
        return list(FALLBACK_FIXERS)


def _build_diff(
    original_content: str,
    refactored: str,
    max_changes: int,
    preview_chars: int,
    numbered: bool,
) -> tuple[int, str]:
    """Build a human-readable diff summary between two versions of a file.

    Args:
        original_content: The original file contents.
        refactored: The refactored file contents.
        max_changes: Maximum number of change lines to include.
        preview_chars: Maximum characters per previewed line.
        numbered: If True, prefix each change with its line number.

    Returns:
        A tuple of (change_count, message) where message may be empty.
    """
    original_lines = original_content.splitlines()
    refactored_lines = refactored.splitlines()
    diff_lines: list[str] = []
    changes = 0
    for i, (orig, new) in enumerate(
        zip(original_lines, refactored_lines, strict=False)
    ):
        if orig != new:
            changes += 1
            if numbered:
                diff_lines.append(
                    f"  Line {i + 1}: {orig[:preview_chars]} -> {new[:preview_chars]}"
                )
            else:
                diff_lines.append(f"  - {orig[:preview_chars]}")
                diff_lines.append(f"  + {new[:preview_chars]}")
    message = f"Changed {changes} line(s)"
    if diff_lines:
        message += "\n" + "\n".join(diff_lines[:max_changes])
    if len(diff_lines) > max_changes:
        message += f"\n  ... and {len(diff_lines) - max_changes} more changes"
    return changes, message


def apply_2to3_fixes(path: str) -> tuple[str, bool, str]:
    """Apply all lib2to3 fixes to a single file.

    Args:
        path: The path to the Python file to refactor.

    Returns:
        A tuple of (path, success, message).
    """
    try:
        path = Path(path)
        original_content = path.read_text(encoding="utf-8")
        all_fixers = get_all_fixers()
        tool = CustomRefactoringTool(fixers=all_fixers, explicit=all_fixers)
        try:
            refactored = tool.refactor_string(original_content, path)
            if refactored and refactored != original_content:
                path.write_text(refactored, encoding="utf-8")
                _, message = _build_diff(
                    original_content,
                    refactored,
                    max_changes=MAX_DIFF_LINES,
                    preview_chars=MAX_CHANGE_PREVIEW_CHARS,
                    numbered=True,
                )
                return path, True, message
            return path, True, "No changes needed"
        except SyntaxError as e:
            return path, False, f"Syntax error in file: {e}"
        except Exception as e:
            return path, False, f"Refactoring error: {e!s}"
    except FileNotFoundError:
        return path, False, "File not found"
    except PermissionError:
        return path, False, "Permission denied"
    except Exception as e:
        return path, False, f"Unexpected error: {e!s}"


def find_python_files(
    paths: Sequence[str], extensions: Sequence[str] | None = None
) -> list[str]:
    """Find all files matching the given extensions under the provided paths.

    Args:
        paths: Files or directories to search.
        extensions: File extensions to include; defaults to [".py"].

    Returns:
        A list of matching file path strings.
    """
    exts = list(extensions) if extensions is not None else list(DEFAULT_EXTENSIONS)
    python_files: list[str] = []
    for path in paths:
        path_obj = Path(path)
        if not path_obj.exists():
            logger.warning(f"Path '{path}' does not exist")
            continue
        if path_obj.is_file():
            if path_obj.suffix in exts:
                python_files.append(str(path_obj))
        elif path_obj.is_dir():
            for ext in exts:
                python_files.extend(str(p) for p in path_obj.rglob(f"*{ext}"))
    return python_files


def process_files_parallel(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """Process all files in parallel using a Pool of workers.

    Args:
        paths: The list of file paths to process.

    Returns:
        A tuple of (successful_files, failed_files).
    """
    successful: list[str] = []
    failed: list[str] = []
    total = len(paths)
    print(f"Processing {total} files using {WORKER_COUNT} workers...")
    print("-" * 40)

    pool = Pool(processes=WORKER_COUNT)
    try:
        async_results = [
            (path, pool.apply_async(apply_2to3_fixes, (path,))) for path in paths
        ]
        for i, (path, result) in enumerate(async_results, 1):
            try:
                result_path, success, message = result.get()
                if success:
                    successful.append(result_path)
                    status = "✓"
                else:
                    failed.append(result_path)
                    status = "✗"
                print(f"[{i}/{total}] {status} {Path(result_path).name}")
                if message != "No changes needed":
                    print(f"    {message}")
            except Exception as e:
                failed.append(path)
                logger.error(f"[{i}/{total}] ✗ {Path(path).name}")
                logger.error(f"    Unexpected error: {e!s}")
    finally:
        pool.close()
        pool.join()
    return successful, failed


def dry_run_file(path: str) -> tuple[str, str, bool]:
    """Preview the changes that would be made to a single file.

    Args:
        path: The path to the Python file to preview.

    Returns:
        A tuple of (path, diff_output, has_changes).
    """
    try:
        original_content = Path(path).read_text(encoding="utf-8")
        all_fixers = get_all_fixers()
        tool = CustomRefactoringTool(fixers=all_fixers, explicit=all_fixers)
        try:
            refactored = tool.refactor_string(original_content, path)
            if refactored and refactored != original_content:
                original_lines = original_content.splitlines()
                refactored_lines = refactored.splitlines()
                diff: list[str] = []
                for orig, new in zip(original_lines, refactored_lines, strict=False):
                    if orig != new:
                        diff.append(f"  - {orig[:MAX_PREVIEW_CHARS]}")
                        diff.append(f"  + {new[:MAX_PREVIEW_CHARS]}")
                if len(original_lines) != len(refactored_lines):
                    diff.append(
                        f"  (Line count changed: {len(original_lines)} -> {len(refactored_lines)})"
                    )
                return path, "\n".join(diff[:MAX_DRY_RUN_DIFF_LINES]), True
            return path, "No changes needed", False
        except SyntaxError as e:
            return path, f"Syntax error: {e}", False
        except Exception as e:
            return path, f"Error: {e!s}", False
    except Exception as e:
        return path, f"Error reading file: {e!s}", False


def perform_dry_run(paths: Sequence[str]) -> None:
    """Preview changes for all files in parallel without applying them.

    Args:
        paths: The list of file paths to preview.
    """
    print(f"\nDRY RUN - Preview of changes using {WORKER_COUNT} workers:")
    print("-" * 40)
    files_with_changes = 0
    pool = Pool(processes=WORKER_COUNT)
    try:
        async_results = [
            (path, pool.apply_async(dry_run_file, (path,))) for path in paths
        ]
        for path, result in async_results:
            try:
                result_path, output, has_changes = result.get()
            except Exception as e:
                logger.error(f"✗ {Path(path).name}: Unexpected error: {e!s}")
                continue
            if has_changes:
                files_with_changes += 1
                print(f"\n📝 {Path(result_path).name}:")
                print(output)
            else:
                print(f"✓ {Path(result_path).name}: {output}")
    finally:
        pool.close()
        pool.join()
    print(f"\n{'=' * 40}")
    print(
        f"Dry run complete: {files_with_changes} of {len(paths)} files would be changed"
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument sequence; defaults to sys.argv[1:].

    Returns:
        The parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(
        description="Apply all available 2to3 fixes to Python files using lib2to3 and multiprocessing"
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to process")
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to process (default: .py)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the script.

    Args:
        argv: Optional argument sequence; defaults to sys.argv[1:].

    Returns:
        Process exit code: 0 on full success, 1 otherwise.
    """
    args = _parse_args(argv)
    python_files = find_python_files(args.paths, args.extensions)
    if not python_files:
        logger.warning("No Python files found to process.")
        return 1
    # Deduplicate while preserving order
    python_files = list(dict.fromkeys(python_files))
    print(f"Found {len(python_files)} Python file(s) to process")
    if args.dry_run:
        perform_dry_run(python_files)
        return 0
    successful, failed = process_files_parallel(python_files)
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total files processed: {len(python_files)}")
    print(f"✓ Successful: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")
    if failed:
        print("\nFailed files:")
        for f in failed:
            print(f"  - {Path(f).name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
