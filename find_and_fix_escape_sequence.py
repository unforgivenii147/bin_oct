#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import os
import tokenize
import warnings
from pathlib import Path


def process_file(path: Path, auto_fix: bool = False) -> dict:
    result = {
        "path": path,
        "has_issues": False,
        "fixed": False,
        "errors": [],
        "warnings": [],
    }
    try:
        content_bytes = path.read_bytes()
    except Exception as e:
        result["errors"].append(f"Could not read file: {e}")
        return result
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(content_bytes, str(path), "exec")
        except SyntaxError as se:
            if "invalid escape sequence" in str(se):
                result["has_issues"] = True
                result["errors"].append(f"Line {se.lineno}: SyntaxError: {se.msg}")
            else:
                return result
        for w in caught_warnings:
            if issubclass(
                w.category, SyntaxWarning
            ) and "invalid escape sequence" in str(w.message):
                result["has_issues"] = True
                line_no = getattr(w, "lineno", "Unknown")
                result["warnings"].append(f"Line {line_no}: SyntaxWarning: {w.message}")
    if result["has_issues"] and auto_fix:
        try:
            modified_tokens = []
            is_modified = False
            with path.open("rb") as f:
                tokens = list(tokenize.tokenize(f.readline))
            for tok in tokens:
                if tok.type == tokenize.STRING:
                    prefix = ""
                    text = tok.string
                    for char in text:
                        if char.lower() in "frub":
                            prefix += char
                        else:
                            break
                    actual_str = text[len(prefix) :]
                    if "\\" in actual_str and "r" not in prefix.lower():
                        with warnings.catch_warnings(record=True) as str_warnings:
                            warnings.simplefilter("always", SyntaxWarning)
                            with contextlib.suppress(SyntaxError, SyntaxWarning):
                                compile(f"_{prefix}{actual_str}", "<string>", "exec")
                            if any(
                                "invalid escape sequence" in str(sw.message)
                                for sw in str_warnings
                            ):
                                new_prefix = (
                                    "r" + prefix
                                    if "r" not in prefix.lower()
                                    else prefix
                                )
                                tok = tok._replace(string=f"{new_prefix}{actual_str}")
                                is_modified = True
                modified_tokens.append(tok)
            if is_modified:
                fixed_bytes = tokenize.untokenize(modified_tokens)
                path.write_bytes(fixed_bytes)
                result["fixed"] = True
        except Exception as e:
            result["errors"].append(f"Failed to auto-fix: {e}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally fix invalid escape sequences in Python files using parallel processing."
    )
    parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=".",
        help="The target directory to scan (default: current directory).",
    )
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically fix invalid escapes by adding an 'r' prefix to offending strings.",
    )
    args = parser.parse_args()
    target_dir = Path(args.directory)
    if not target_dir.is_dir():
        print(f"❌ Error: {target_dir} is not a valid directory.")
        return
    py_files = list(target_dir.rglob("*.py"))
    script_path = Path(__file__).resolve()
    py_files = [f for f in py_files if f.resolve() != script_path]
    print(
        f"🔍 Found {len(py_files)} Python files. Processing in parallel across {os.cpu_count() or 1} cores..."
    )
    if args.auto_fix:
        print(
            "🛠️  Auto-fix flag (-a) is active. Offending string literals will be converted to raw strings."
        )
    print("-" * 40)
    total_issues = 0
    total_fixed = 0
    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_file, f, args.auto_fix): f for f in py_files}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            path_rel = res["path"].relative_to(target_dir)
            if res["has_issues"]:
                total_issues += 1
                status = "🔧 FIXED" if res["fixed"] else "⚠️  WARNING"
                print(f"[{status}] {path_rel}")
                for w in res["warnings"]:
                    print(f"   -> {w}")
                for e in res["errors"]:
                    print(f"   -> {e}")
                if res["fixed"]:
                    total_fixed += 1
                print()
    print("-" * 40)
    print("📊 Scan Complete.")
    print(f"   Files with issues: {total_issues}")
    if args.auto_fix:
        print(f"   Files successfully fixed: {total_fixed}")


if __name__ == "__main__":
    raise SystemExit(main())
