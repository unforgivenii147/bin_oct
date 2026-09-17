#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that removes duplicate top-level functions from Python
files by comparing them against a reference file. The script should:

- Use argparse to accept a reference .py file, zero or more target files/dirs
  (defaulting to the current directory), and an -a/--apply flag for dry-run vs
  actual removal.
- Parse each file with the ast module, extract top-level FunctionDef nodes,
  and compute an MD5 hash of each function's normalized body plus its argument
  and return annotations.
- Normalize bodies by stripping common leading indentation and blank lines.
- Use multiprocessing.Pool with apply_async and a fixed pool of 8 workers to
  process target files concurrently (no CLI flags controlling parallelism).
- Report per-file status (skipped, ok, found, updated, error) using loguru.
- When applying, delete duplicate functions (including preceding decorators and
  blank lines) from the bottom of each file upward to keep line numbers valid.
- Use pathlib exclusively for all path handling, with full type annotations
  throughout so the code passes a strict type checker.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from collections.abc import Sequence
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# Number of worker processes used for parallel file processing.
POOL_SIZE: int = 8


def normalize_function_body(lines: Sequence[str], start_idx: int, end_idx: int) -> str:
    """Return the function body lines with common leading indentation removed.

    Args:
        lines: All lines of the source file.
        start_idx: Index of the first body line.
        end_idx: Index one past the last body line.

    Returns:
        A normalized, dedented string containing only non-blank lines joined
        by newlines, or an empty string if there is no body.
    """
    body_lines: list[str] = list(lines[start_idx:end_idx])
    if not body_lines:
        return ""
    stripped: list[str] = [line for line in body_lines if line.strip()]
    if not stripped:
        return ""
    min_indent: int = min(len(line) - len(line.lstrip()) for line in stripped)
    return "\n".join(line[min_indent:] if line.strip() else "" for line in body_lines)


def compute_function_hash(path: Path, func_node: ast.FunctionDef) -> str | None:
    """Compute an MD5 hash for a top-level function definition.

    The hash covers the function's signature (arguments and return
    annotation) plus its normalized body.

    Args:
        path: Path to the source file containing the function.
        func_node: The AST node for the function.

    Returns:
        A hexadecimal MD5 digest, or None if the file could not be read.
    """
    try:
        lines: list[str] = path.read_text().splitlines(keepends=True)
    except Exception:
        return None

    start_line: int = func_node.lineno - 1
    end_line: int = (
        func_node.end_lineno if func_node.end_lineno is not None else start_line + 1
    )
    func_lines: list[str] = lines[start_line:end_line]

    body_start: int = 0
    for i, line in enumerate(func_lines):
        if ":" in line and not line.strip().startswith("@"):
            body_start = i + 1
            break

    sig: str = ast.dump(func_node.args)
    if func_node.returns:
        sig += ast.dump(func_node.returns)

    body: str = normalize_function_body(func_lines, body_start, len(func_lines))
    content: str = f"{sig}\n{body}"
    return hashlib.md5(content.encode()).hexdigest()


def extract_top_level_functions(
    path: Path,
) -> dict[str, dict[str, Any]] | None:
    """Extract all top-level function definitions from a Python file.

    Args:
        path: Path to the Python file.

    Returns:
        A mapping of function name to a dict containing name, hash, lineno,
        and end_lineno, or None if the file could not be parsed.
    """
    try:
        tree: ast.Module = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return None
    except Exception:
        return None

    functions: dict[str, dict[str, Any]] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            content_hash: str | None = compute_function_hash(path, node)
            if content_hash:
                functions[node.name] = {
                    "name": node.name,
                    "hash": content_hash,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                }
    return functions


def process_target_file(
    target_path: Path,
    ref_hashes: dict[str, str],
    apply: bool = False,
) -> dict[str, Any]:
    """Process a single target file, optionally removing duplicate functions.

    Args:
        target_path: Path to the target file.
        ref_hashes: Mapping of reference function hash to reference name.
        apply: If True, remove duplicates from the file; otherwise dry-run.

    Returns:
        A result dict with keys: file, status, duplicates, and optionally error.
    """
    funcs: dict[str, dict[str, Any]] | None = extract_top_level_functions(target_path)
    if funcs is None or not funcs:
        return {"file": target_path, "status": "skipped", "duplicates": []}

    duplicates: list[dict[str, Any]] = []
    for func_name, func_info in funcs.items():
        if func_info["hash"] in ref_hashes:
            duplicates.append(
                {
                    "name": func_name,
                    "lineno": func_info["lineno"],
                    "end_lineno": func_info["end_lineno"],
                    "ref_name": ref_hashes[func_info["hash"]],
                }
            )

    if not duplicates:
        return {"file": target_path, "status": "ok", "duplicates": []}

    if apply:
        try:
            lines: list[str] = target_path.read_text().splitlines(keepends=True)
            duplicates.sort(key=lambda x: x["lineno"], reverse=True)
            removed: list[str] = []
            for dup in duplicates:
                start: int = dup["lineno"] - 1
                end: int = dup["end_lineno"]
                while start > 0 and (
                    lines[start - 1].strip().startswith("@")
                    or lines[start - 1].strip() == ""
                ):
                    start -= 1
                del lines[start:end]
                removed.append(dup["name"])
            target_path.write_text("".join(lines))
            return {
                "file": target_path,
                "status": "updated",
                "duplicates": removed,
            }
        except Exception as e:
            return {
                "file": target_path,
                "status": "error",
                "error": str(e),
                "duplicates": [],
            }

    return {"file": target_path, "status": "found", "duplicates": duplicates}


def expand_input_paths(inputs: Sequence[str]) -> list[Path]:
    """Expand CLI inputs into a sorted list of unique Python files.

    Args:
        inputs: File or directory path strings from the CLI.

    Returns:
        A sorted list of Path objects for all matching .py files.
    """
    py_files: set[Path] = set()
    if not inputs:
        py_files.update(Path(".").rglob("*.py"))
    else:
        for item in inputs:
            path: Path = Path(item)
            if path.is_file() and path.suffix == ".py":
                py_files.add(path)
            elif path.is_dir():
                py_files.update(path.rglob("*.py"))
    return sorted(py_files)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional sequence of argument strings (defaults to sys.argv[1:]).

    Returns:
        The parsed argparse.Namespace.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Remove duplicate functions from Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s ref.py module.py\n"
            "  %(prog)s ref.py src/\n"
            "  %(prog)s ref.py  # scan current dir\n"
            "  %(prog)s -a ref.py target.py  # actually remove"
        ),
    )
    parser.add_argument("reference", help="Reference file (functions to keep)")
    parser.add_argument(
        "inputs", nargs="*", help="Target files/directories (default: .)"
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the duplicate-function remover.

    Args:
        argv: Optional sequence of argument strings.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    args: argparse.Namespace = parse_args(argv)

    ref_path: Path = Path(args.reference)
    if not ref_path.exists():
        logger.error(f"❌ Reference file not found: {ref_path}")
        return 1
    if ref_path.suffix != ".py":
        logger.error("❌ Reference must be a .py file")
        return 1

    print(f"📖 Analyzing reference: {ref_path}")
    ref_funcs: dict[str, dict[str, Any]] | None = extract_top_level_functions(ref_path)
    if ref_funcs is None:
        logger.error("❌ Failed to parse reference file")
        return 1
    if not ref_funcs:
        logger.warning("⚠️  No functions found in reference")
        return 1

    ref_hashes: dict[str, str] = {
        info["hash"]: info["name"] for info in ref_funcs.values()
    }
    print(f"  Found {len(ref_hashes)} functions")

    target_files: list[Path] = expand_input_paths(args.inputs)
    target_files = [f for f in target_files if f != ref_path]
    if not target_files:
        logger.warning("⚠️  No target files found")
        return 0

    mode: str = "applying" if args.apply else "scanning"
    print(f"\n🔍 {mode} {len(target_files)} file(s)...")
    print("-" * 40)

    total_duplicates: int = 0
    total_updated: int = 0

    with Pool(processes=POOL_SIZE) as pool:
        async_results: list[Any] = [
            pool.apply_async(process_target_file, (f, ref_hashes, args.apply))
            for f in target_files
        ]
        for async_result in async_results:
            result: dict[str, Any] = async_result.get()
            status: str = result["status"]
            if status == "skipped":
                print(f"⊘  {result['file']}")
            elif status == "ok":
                print(f"✅ {result['file']}")
            elif status == "found":
                total_duplicates += len(result["duplicates"])
                names: str = ", ".join(d["name"] for d in result["duplicates"])
                logger.warning(f"⚠️  {result['file']}: {names}")
            elif status == "updated":
                total_updated += len(result["duplicates"])
                names = ", ".join(result["duplicates"])
                print(f"✂️  {result['file']}: removed {names}")
            elif status == "error":
                logger.error(f"❌ {result['file']}: {result['error']}")

    print("-" * 40)
    if args.apply:
        print(f"✅ Removed {total_updated} duplicate(s)")
    else:
        print(f"ℹ️  Found {total_duplicates} duplicate function(s)")
        print("   Run with -a/--apply to remove")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
