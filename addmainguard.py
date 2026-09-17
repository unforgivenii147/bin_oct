#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI tool that scans a directory tree for Python files missing
an `if __name__ == "__main__":` guard, and optionally injects a `main()`
function and guard into them.

The tool uses `multiprocessing.Pool.apply_async` with a fixed pool of 8
workers, `pathlib` for all filesystem access, `loguru` for logging, full
type annotations, and `argparse` for the CLI. It supports `--add`, `--dry-run`,
and `--exclude` flags. The script itself must remain runnable via a
`if __name__ == "__main__":` guard.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final, Literal, TypedDict

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDES: Final[tuple[str, ...]] = (
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
)

POOL_SIZE: Final[int] = 8

MAIN_GUARD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"if\s+__name__\s*==\s*[\"\']__main__[\"\']\s*:"
)

MAIN_FUNC_TEMPLATE: Final[str] = (
    "\n\ndef main() -> None:\n"
    '    """Entry point for the script."""\n'
    "    # TODO: Add your main logic here\n"
    '    print("Hello from main!")\n'
)

MAIN_GUARD_TEMPLATE: Final[str] = (
    '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
)

Status = Literal["skipped", "missing", "would_add", "added", "error"]


class ProcessResult(TypedDict):
    """Structured result returned by `process_file`."""

    status: Status
    message: str
    path: Path


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def has_main_guard(content: str) -> bool:
    """Return True if *content* already contains an `if __name__ == "__main__"` guard."""
    return bool(MAIN_GUARD_PATTERN.search(content))


def add_main_function(content: str) -> str:
    """Insert a stub `main()` function after the last top-level import, if missing."""
    if "def main(" in content:
        return content

    lines: list[str] = content.split("\n")
    insert_pos: int = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            insert_pos = i + 1
        elif stripped and insert_pos == 0:
            insert_pos = 0

    lines.insert(insert_pos, MAIN_FUNC_TEMPLATE)
    return "\n".join(lines)


def add_main_guard(content: str) -> str:
    """Append a `if __name__ == "__main__":` guard to *content* if missing."""
    if has_main_guard(content):
        return content
    return content.rstrip() + MAIN_GUARD_TEMPLATE


def process_file(path: Path, add: bool = False, dry_run: bool = False) -> ProcessResult:
    """Inspect (and optionally rewrite) a single Python file.

    Returns a `ProcessResult` describing the outcome.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(f"Failed to read {path}: {exc}")
        return {"status": "error", "message": str(exc), "path": path}

    if has_main_guard(content):
        return {"status": "skipped", "message": "Already has guard", "path": path}

    if not add:
        return {"status": "missing", "message": "Missing guard", "path": path}

    new_content = add_main_guard(add_main_function(content))

    if dry_run:
        return {"status": "would_add", "message": "Would add guard", "path": path}

    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        logger.error(f"Failed to write {path}: {exc}")
        return {"status": "error", "message": str(exc), "path": path}

    return {"status": "added", "message": "Added guard successfully", "path": path}


def find_python_files(
    directory: Path,
    exclude_patterns: Sequence[str] = DEFAULT_EXCLUDES,
) -> list[Path]:
    """Recursively find `.py` files under *directory*, skipping excluded path parts."""
    if not directory.exists():
        logger.warning(f"Directory does not exist: {directory}")
        return []

    excluded: frozenset[str] = frozenset(exclude_patterns)
    results: list[Path] = []
    for path in directory.rglob("*.py"):
        if excluded.intersection(path.parts):
            continue
        results.append(path)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="Find and optionally add main guard to Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "\nExamples:\n"
            "  %(prog)s                    # Find missing guards in current directory\n"
            "  %(prog)s -a                 # Add guards to all missing files\n"
            "  %(prog)s src/ -a            # Check src/ directory and add guards\n"
            "  %(prog)s -a --dry-run       # Preview changes without modifying\n"
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--add",
        action="store_true",
        help="Add the main guard to missing files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without actually modifying files",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Additional directories to exclude",
    )
    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the scanner/injector CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args()

    directory = Path(args.directory).resolve()
    exclude_patterns: tuple[str, ...] = DEFAULT_EXCLUDES + tuple(args.exclude)

    print(f"📂 Scanning: {directory}")
    print(f"🚫 Excluding: {', '.join(exclude_patterns)}")
    print(f"⚡ Using {POOL_SIZE} parallel workers")

    py_files = find_python_files(directory, exclude_patterns)
    total = len(py_files)

    if total == 0:
        logger.warning("⚠️  No Python files found!")
        return 0

    print(f"📄 Found {total} Python files")

    results: dict[str, list[Path | tuple[Path, str]]] = {
        "skipped": [],
        "missing": [],
        "added": [],
        "would_add": [],
        "errors": [],
    }

    pool = Pool(processes=POOL_SIZE)
    try:
        async_results: list[AsyncResult[ProcessResult]] = [
            pool.apply_async(process_file, (path, args.add, args.dry_run))
            for path in py_files
        ]

        completed = 0
        for ar in async_results:
            result: ProcessResult = ar.get()
            completed += 1
            if completed % 10 == 0 or completed == total:
                print(f"⏳ Processing: {completed}/{total}")

            status = result["status"]
            path = result["path"]
            if status == "skipped":
                results["skipped"].append(path)
            elif status == "missing":
                results["missing"].append(path)
            elif status == "added":
                results["added"].append(path)
            elif status == "would_add":
                results["would_add"].append(path)
            elif status == "error":
                results["errors"].append((path, result["message"]))
    finally:
        pool.close()
        pool.join()

    has_guard = len(results["skipped"])

    if args.add:
        added = len(results["added"])
        would_add = len(results["would_add"])
        errors = len(results["errors"])

        print("📊 Results:")
        print(f"  ✅ Already had guard: {has_guard}")
        if args.dry_run:
            print(f"  🔍 Would add guard: {would_add}")
        else:
            print(f"  ➕ Added guard: {added}")
        print(f"  ❌ Errors: {errors}")

        if errors > 0:
            logger.error("❌ Errors encountered:")
            for path, error in results["errors"]:  # type: ignore[misc]
                logger.error(f"  {path}: {error}")

        if args.dry_run and would_add > 0:
            print(f"🔍 Dry run complete: Would have modified {would_add} files")
            print("   Run without --dry-run to apply changes")
    else:
        missing = len(results["missing"])
        print(f"📋 Found {missing} files without the main guard:")
        for path in sorted(results["missing"]):  # type: ignore[arg-type]
            path_obj = Path(path)
            try:
                rel_path = (
                    path_obj.relative_to(directory)
                    if directory != Path(".")
                    else path_obj
                )
            except ValueError:
                rel_path = path_obj
            print(f"  {rel_path}")
        if missing > 0:
            print(
                f"💡 Run with -a to add the guard: python {sys.argv[0]} {args.directory} -a"
            )
        else:
            print("✅ All Python files have the main guard!")

    if args.add and not args.dry_run and results["added"]:
        print(f"✅ Successfully added main guard to {len(results['added'])} files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
