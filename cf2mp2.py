#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import difflib
import multiprocessing as mp
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

WORKERS = 8
MAX_FILE_SIZE = 1024 * 1024
PYTHON_EXTENSIONS = {".py", ".pyw", ".pyi"}
IMPORT_PATTERNS = [
    re.compile(
        r"^(\s*)from\s+concurrent\.futures\s+import\s+"
        r"([^#\n]*ThreadPoolExecutor[^#\n]*)$",
        re.MULTILINE,
    ),
    re.compile(
        r"^(\s*)from\s+concurrent\.futures\s+import\s+"
        r"([^#\n]*ProcessPoolExecutor[^#\n]*)$",
        re.MULTILINE,
    ),
    re.compile(r"^(\s*)import\s+concurrent\.futures\s*$", re.MULTILINE),
    re.compile(
        r"^(\s*)from\s+concurrent\.futures\s+import\s+"
        r"([^#\n]*)(as_completed|wait|Future|Executor|ALL_COMPLETED|FIRST_COMPLETED)[^#\n]*$",
        re.MULTILINE,
    ),
]
THREAD_POOL_PATTERN = re.compile(
    r"(\bThreadPoolExecutor\s*\()\s*" r"(?:max_workers\s*=\s*)?(\d+)?\s*\)?",
    re.MULTILINE,
)
PROCESS_POOL_PATTERN = re.compile(
    r"(\bProcessPoolExecutor\s*\()\s*" r"(?:max_workers\s*=\s*)?(\d+)?\s*\)?",
    re.MULTILINE,
)
SUBMIT_PATTERN = re.compile(
    r"(\w+)\s*\.\s*submit\s*\(\s*" r"([^,]+)\s*(?:,\s*([^)]*?))?\)",
    re.MULTILINE,
)
EXECUTOR_MAP_PATTERN = re.compile(r"(\w+)\s*\.\s*map\s*\(", re.MULTILINE)
AS_COMPLETED_PATTERN = re.compile(r"(\b)as_completed\s*\(", re.MULTILINE)
WITH_EXECUTOR_PATTERN = re.compile(
    r"with\s+(ThreadPoolExecutor|ProcessPoolExecutor)\s*\([^)]*\)\s+as\s+(\w+)\s*:",
    re.MULTILINE,
)
SHUTDOWN_PATTERN = re.compile(r"(\w+)\s*\.\s*shutdown\s*\([^)]*\)\s*", re.MULTILINE)
FUTURE_RESULT_PATTERN = re.compile(r"(\w+)\s*\.\s*result\s*\(\s*\)", re.MULTILINE)
FUTURE_DONE_PATTERN = re.compile(r"(\w+)\s*\.\s*done\s*\(\s*\)", re.MULTILINE)
FUTURE_CANCELLED_PATTERN = re.compile(r"(\w+)\s*\.\s*cancelled\s*\(\s*\)", re.MULTILINE)
FUTURE_CANCEL_PATTERN = re.compile(r"(\w+)\s*\.\s*cancel\s*\(\s*\)", re.MULTILINE)
FUTURE_EXCEPTION_PATTERN = re.compile(r"(\w+)\s*\.\s*exception\s*\(\s*\)", re.MULTILINE)


@dataclass
class FileResult:
    path: Path
    original: str
    converted: str
    error: str | None = None
    changed: bool = False

    @property
    def diff(self) -> str:
        if not self.changed:
            return ""
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.converted.splitlines(keepends=True),
                fromfile=str(self.path),
                tofile=f"{self.path} (converted)",
            )
        )


def collect_python_files(paths: Sequence[Path]) -> list[Path]:
    files: set[Path] = set()
    if not paths:
        paths = [Path(".")]
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in PYTHON_EXTENSIONS:
                files.add(path.resolve())
        elif path.is_dir():
            for ext in PYTHON_EXTENSIONS:
                files.update(p.resolve() for p in path.rglob(f"*{ext}"))
        else:
            print(f"Warning: {path} does not exist", file=sys.stderr)
    return sorted(files)


def convert_imports(content: str) -> str:
    lines = content.splitlines(keepends=True)
    new_lines = []
    has_futures_import = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        is_futures_import = False
        for pattern in IMPORT_PATTERNS:
            if pattern.search(line):
                is_futures_import = True
                has_futures_import = True
                break
        if is_futures_import:
            if not any("multiprocessing" in l for l in new_lines):
                new_lines.append("import multiprocessing as mp\n")
            continue
        new_lines.append(line)
    result = "".join(new_lines)
    if has_futures_import and "multiprocessing" not in result:
        lines = result.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("import ") or line.strip().startswith("from "):
                insert_idx = i + 1
        lines.insert(insert_idx, "import multiprocessing as mp\n")
        result = "".join(lines)
    return result


def convert_executor_instantiation(content: str) -> str:
    def replace_pool(match: re.Match) -> str:
        return f"{match.group(1)[:0]}mp.Pool(processes=8)"

    content = WITH_EXECUTOR_PATTERN.sub(
        lambda m: f"with mp.Pool(processes=8) as {m.group(2)}:", content
    )
    content = THREAD_POOL_PATTERN.sub(lambda m: "mp.Pool(processes=8)", content)
    content = PROCESS_POOL_PATTERN.sub(lambda m: "mp.Pool(processes=8)", content)
    return content


def convert_submit_calls(content: str) -> str:
    def replace_submit(match: re.Match) -> str:
        executor_name = match.group(1)
        func_name = match.group(2).strip()
        args = match.group(3).strip() if match.group(3) else ""
        if args:
            if "=" in args and "," not in args:
                return f"{executor_name}.apply_async({func_name}, kwds={{{args}}})"
            else:
                return f"{executor_name}.apply_async({func_name}, args=({args},))"
        else:
            return f"{executor_name}.apply_async({func_name})"

    return SUBMIT_PATTERN.sub(replace_submit, content)


def convert_map_calls(content: str) -> str:
    content = EXECUTOR_MAP_PATTERN.sub(lambda m: f"{m.group(1)}.map(", content)
    return content


def convert_shutdown_calls(content: str) -> str:
    def replace_shutdown(match: re.Match) -> str:
        pool_name = match.group(1)
        return f"{pool_name}.close()\n{pool_name}.join()"

    return SHUTDOWN_PATTERN.sub(replace_shutdown, content)


def convert_as_completed(content: str) -> str:
    if AS_COMPLETED_PATTERN.search(content):
        content = AS_COMPLETED_PATTERN.sub(
            lambda m: (
                f"{m.group(1)}# TODO: Convert as_completed to apply_async with callback\nas_completed("
            ),
            content,
        )
    return content


def convert_future_methods(content: str) -> str:
    content = FUTURE_RESULT_PATTERN.sub(lambda m: f"{m.group(1)}.get()", content)
    content = FUTURE_DONE_PATTERN.sub(lambda m: f"{m.group(1)}.ready()", content)
    content = FUTURE_CANCELLED_PATTERN.sub(
        lambda m: (
            f"{m.group(1)}.successful()  # Note: successful() is inverse of cancelled()"
        ),
        content,
    )
    content = FUTURE_CANCEL_PATTERN.sub(
        lambda m: (
            f"{m.group(1)}.wait(timeout=0)  # Note: cancel() not supported in apply_async"
        ),
        content,
    )
    content = FUTURE_EXCEPTION_PATTERN.sub(
        lambda m: f"{m.group(1)}.get()  # Note: will raise exception if task failed",
        content,
    )
    return content


def convert_python_file(content: str) -> str:
    result = content
    result = convert_imports(result)
    result = convert_executor_instantiation(result)
    result = convert_submit_calls(result)
    result = convert_map_calls(result)
    result = convert_shutdown_calls(result)
    result = convert_as_completed(result)
    result = convert_future_methods(result)
    return result


def process_file(path: Path) -> FileResult:
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            return FileResult(
                path=path,
                original="",
                converted="",
                error=f"File too large (> {MAX_FILE_SIZE} bytes)",
                changed=False,
            )
        content = path.read_text(encoding="utf-8")
        if not any(
            "ThreadPoolExecutor" in content
            or "ProcessPoolExecutor" in content
            or "concurrent.futures" in content
            or "as_completed" in content
            for _ in [0]
        ):
            return FileResult(
                path=path, original=content, converted=content, changed=False
            )
        converted = convert_python_file(content)
        return FileResult(
            path=path,
            original=content,
            converted=converted,
            changed=content != converted,
        )
    except UnicodeDecodeError as e:
        return FileResult(
            path=path,
            original="",
            converted="",
            error=f"Unicode decode error: {e}",
            changed=False,
        )
    except Exception as e:
        return FileResult(
            path=path,
            original="",
            converted="",
            error=f"Unexpected error: {e}",
            changed=False,
        )


def process_file_wrapper(args: tuple[Path, bool]) -> FileResult:
    path, apply_flag = args
    result = process_file(path)
    if apply_flag and result.changed and not result.error:
        try:
            path.write_text(result.converted, encoding="utf-8")
            print(f"✓ Converted: {path}", flush=True)
        except Exception as e:
            result.error = f"Failed to write file: {e}"
    return result


def print_diff(result: FileResult) -> None:
    if result.error:
        print(f"✗ Error processing {result.path}: {result.error}", file=sys.stderr)
        return
    if result.changed:
        print(f"--- {result.path}")
        print(result.diff)
        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert concurrent.futures patterns to multiprocessing.Pool.apply_async",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply changes in-place (default: dry-run with diff)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help=f"Number of worker processes (default: {WORKERS})",
    )
    args = parser.parse_args()
    if args.workers < 1:
        print("Error: workers must be >= 1", file=sys.stderr)
        return 1
    if args.workers > mp.cpu_count() * 2:
        print(
            f"Warning: {args.workers} workers exceeds 2x CPU count ({mp.cpu_count()})",
            file=sys.stderr,
        )
    try:
        files = collect_python_files(args.paths)
    except Exception as e:
        print(f"Error collecting files: {e}", file=sys.stderr)
        return 1
    if not files:
        print("No Python files found to process.")
        return 0
    print(f"Processing {len(files)} Python file(s) with {args.workers} workers...")
    if not args.apply:
        print("Dry-run mode (use -a to apply changes)\n")
    work_items = [(path, args.apply) for path in files]
    results: list[FileResult] = []
    changed_count = 0
    error_count = 0
    try:
        with mp.Pool(processes=args.workers) as pool:
            for result in pool.imap_unordered(
                process_file_wrapper, work_items, chunksize=10
            ):
                results.append(result)
                if result.error:
                    error_count += 1
                    print(
                        f"✗ {result.path}: {result.error}", file=sys.stderr, flush=True
                    )
                elif result.changed:
                    changed_count += 1
                    if not args.apply:
                        print_diff(result)
    except KeyboardInterrupt:
        print("\nInterrupted. Terminating...", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error during processing: {e}", file=sys.stderr)
        return 1
    results.sort(key=lambda r: str(r.path))
    print(f"\n{'=' * 40}")
    print(f"Summary:")
    print(f"  Total files processed: {len(results)}")
    print(f"  Files changed:         {changed_count}")
    print(f"  Files with errors:     {error_count}")
    if args.apply:
        print(f"  Changes applied:       ✓ (in-place)")
    else:
        print(f"  Changes applied:       ✗ (dry-run)")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
