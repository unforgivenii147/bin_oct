#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import os
import tokenize
import warnings
from pathlib import Path


def check_file(path: Path) -> tuple[bool, list[str]]:
    has_issues = False
    messages = []
    try:
        content_bytes = path.read_bytes()
    except Exception as e:
        return False, [f"Error reading file: {e}"]
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(content_bytes, str(path), "exec")
        except SyntaxError as se:
            if "invalid escape sequence" in str(se):
                has_issues = True
                messages.append(f"Line {se.lineno}: SyntaxError: {se.msg}")
        for w in caught_warnings:
            if issubclass(
                w.category, SyntaxWarning
            ) and "invalid escape sequence" in str(w.message):
                has_issues = True
                line_no = getattr(w, "lineno", "Unknown")
                messages.append(f"Line {line_no}: SyntaxWarning: {w.message}")
    return has_issues, messages


def fix_file(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            tokens = list(tokenize.tokenize(f.readline))
    except Exception as e:
        print(f"  [!] Tokenize error in {path.name}: {e}")
        return False
    modified_tokens = []
    is_modified = False
    for tok in tokens:
        if tok.type == tokenize.STRING:
            text = tok.string
            prefix = ""
            for char in text:
                if char.lower() in "frub":
                    prefix += char
                else:
                    break
            actual_str = text[len(prefix) :]
            if "\\" in actual_str and "r" not in prefix.lower():
                new_prefix = "r" + prefix
                with warnings.catch_warnings(record=True) as token_warnings:
                    warnings.simplefilter("always", SyntaxWarning)
                    with contextlib.suppress(SyntaxError, SyntaxWarning):
                        compile(f"_{new_prefix}{actual_str}", "<string>", "exec")
                    has_invalid = any(
                        "invalid escape sequence" in str(tw.message)
                        for tw in token_warnings
                    )
                    if not has_invalid:
                        tok = tok._replace(string=f"{new_prefix}{actual_str}")
                        is_modified = True
        modified_tokens.append(tok)
    if is_modified:
        try:
            fixed_bytes = tokenize.untokenize(modified_tokens)
            path.write_bytes(fixed_bytes)
            return True
        except Exception as e:
            print(f"  [!] Error writing fixed content to {path.name}: {e}")
    return False


def process_file(path: Path, auto_fix: bool) -> dict:
    result = {"path": path, "has_issues": False, "fixed": False, "messages": []}
    has_issues, messages = check_file(path)
    result["has_issues"] = has_issues
    result["messages"] = messages
    if has_issues and auto_fix:
        result["fixed"] = fix_file(path)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Recursively scan and fix Python files for invalid escape sequences."
    )
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically fix issues by converting offending string literals to raw strings.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory).",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    script_path = Path(__file__).resolve()
    issues_count = 0
    fixed_count = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if path.resolve() == script_path:
                continue
            print(f"Processing {path.name}...")
            res = process_file(path, args.auto_fix)
            if res["has_issues"]:
                issues_count += 1
                status = "[🔧 FIXED]" if res["fixed"] else "[⚠️  ISSUE]"
                print(f"{status} {res['path']}")
                for msg in res["messages"]:
                    print(f"   -> {msg}")
                if res["fixed"]:
                    fixed_count += 1
                print()
    print("=" * 40)
    print("📊 Summary:")
    print(f"   Files with invalid escape sequences: {issues_count}")
    if args.auto_fix:
        print(f"   Files successfully auto-fixed:     {fixed_count}")


if __name__ == "__main__":
    raise SystemExit(main())
