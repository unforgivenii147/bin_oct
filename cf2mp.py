#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import difflib
import multiprocessing
import re
import sys
from pathlib import Path
from typing import Any

CM_PATTERN = re.compile(
    r"\bwith\s+(?:ThreadPoolExecutor|ProcessPoolExecutor)\s*"
    r"\([^()]* (?: \( [^()]* \) [^()]* )* \)\s*"
    r"as\s+(\w+)\s*:",
    re.DOTALL | re.VERBOSE,
)
IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
}


def transform_code(code: str) -> tuple[str, bool]:
    original_code = code
    pool_vars = CM_PATTERN.findall(code)
    if not pool_vars:
        return code, False
    code = CM_PATTERN.sub(r"with multiprocessing.Pool(processes=8) as \1:", code)
    for var in pool_vars:
        code = re.sub(rf"\b{var}\.map\(", f"{var}.imap_unordered(", code)
        code = re.sub(rf"\b{var}\.submit\(", f"{var}.apply_async(", code)
        code = re.sub(
            rf"\bas_completed\(\s*{var}\b",
            f"# TODO: multiprocessing has no as_completed. Use {
                var
            }.imap_unordered or loop with .get()\n# as_completed({var}",
            code,
        )
    code = re.sub(
        r"^[ \t]*from\s+concurrent\.futures\s+import\s+.*?\n",
        "",
        code,
        flags=re.MULTILINE,
    )
    if "import multiprocessing" not in code and "from multiprocessing" not in code:
        code = "import multiprocessing\n" + code
    if "apply_async" in code and "MIGRATION NOTE" not in code:
        note = "# MIGRATION NOTE: apply_async requires args as a tuple: pool.apply_async(func, (arg1, arg2))\n"
        code = note + code
    return code, code != original_code


def process_file(args: tuple[Path, bool]) -> dict[str, Any]:
    path, apply_changes = args
    result = {"path": str(path), "changed": False, "diff": "", "error": None}
    try:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1")
        new_content, changed = transform_code(content)
        if changed:
            result["changed"] = True
            diff = difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
            result["diff"] = "".join(diff)
            if apply_changes:
                try:
                    path.write_text(new_content, encoding="utf-8")
                except UnicodeEncodeError:
                    path.write_text(new_content, encoding="latin-1")
    except Exception as e:
        result["error"] = str(e)
    return result


def collect_python_files(paths: list[Path]) -> list[Path]:
    files = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            for f in p.rglob("*.py"):
                if not any(part in IGNORE_DIRS for part in f.parts):
                    files.append(f)
    return files


def main():
    parser = argparse.ArgumentParser(
        description="Migrate concurrent.futures to multiprocessing.Pool."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process. Defaults to current directory.",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply changes in-place. Default is dry-run (shows diff).",
    )
    args = parser.parse_args()
    target_paths = args.paths if args.paths else [Path(".")]
    files = collect_python_files(target_paths)
    if not files:
        print("No Python files found to process.")
        return
    print(f"Found {len(files)} Python file(s). Processing with 8 workers...")
    print("Mode: APPLY (In-place)" if args.apply else "Mode: DRY-RUN (Diff only)")
    print("-" * 40)
    tasks = [(f, args.apply) for f in files]
    changed_count = 0
    error_count = 0
    with multiprocessing.Pool(processes=8) as pool:
        for res in pool.imap_unordered(process_file, tasks):
            if res["error"]:
                print(
                    f"ERROR processing {res['path']}: {res['error']}", file=sys.stderr
                )
                error_count += 1
            elif res["changed"]:
                changed_count += 1
                print(f"\n--- Modified: {res['path']} ---")
                print(res["diff"])
    print("-" * 40)
    print(f"Summary: {changed_count} file(s) modified, {error_count} error(s).")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
