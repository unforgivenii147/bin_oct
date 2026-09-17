#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import os
import tokenize
import warnings
from collections.abc import Iterator
from pathlib import Path


def walk_python_files(root: Path) -> Iterator[Path]:
    for directory, _, filenames in os.walk(root):
        directory_path = Path(directory)
        for filename in filenames:
            path = directory_path / filename
            if path.is_symlink() or ".git" in path.parts:
                continue
            if path.suffix == ".py":
                yield path


def process_file(path: Path, auto_fix: bool = False) -> dict:
    result = {
        "path": path,
        "has_issues": False,
        "fixed": False,
        "messages": [],
    }
    try:
        source_bytes = path.read_bytes()
    except Exception as exc:
        result["messages"].append(f"Error reading file: {exc}")
        return result
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(source_bytes, str(path), "exec")
        except SyntaxError as exc:
            if "invalid escape sequence" in str(exc):
                result["has_issues"] = True
                result["messages"].append(f"Line {exc.lineno}: SyntaxError: {exc.msg}")
            else:
                return result
    for warning in caught_warnings:
        if issubclass(
            warning.category, SyntaxWarning
        ) and "invalid escape sequence" in str(warning.message):
            result["has_issues"] = True
            line_number = getattr(warning, "lineno", "Unknown")
            result["messages"].append(
                f"Line {line_number}: SyntaxWarning: {warning.message}"
            )
    if not result["has_issues"] or not auto_fix:
        return result
    try:
        modified_tokens = []
        source_modified = False
        with path.open("rb") as source_file:
            tokens = tokenize.tokenize(source_file.readline)
            tokens = list(tokens)
        for token in tokens:
            if token.type != tokenize.STRING:
                modified_tokens.append(token)
                continue
            string_text = token.string
            prefix_end = 0
            while (
                prefix_end < len(string_text)
                and string_text[prefix_end].lower() in "frub"
            ):
                prefix_end += 1
            prefix = string_text[:prefix_end]
            literal = string_text[prefix_end:]
            if "\\" not in literal or "r" in prefix.lower():
                modified_tokens.append(token)
                continue
            causes_invalid_escape = False
            with warnings.catch_warnings(record=True) as token_warnings:
                warnings.simplefilter("always", SyntaxWarning)
                with contextlib.suppress(SyntaxError):
                    compile(
                        f"_{prefix}{literal}",
                        "<string>",
                        "exec",
                    )
            for warning in token_warnings:
                if issubclass(
                    warning.category, SyntaxWarning
                ) and "invalid escape sequence" in str(warning.message):
                    causes_invalid_escape = True
                    break
            if causes_invalid_escape:
                new_string = f"r{prefix}{literal}"
                token = token._replace(string=new_string)
                source_modified = True
            modified_tokens.append(token)
        if source_modified:
            fixed_source = tokenize.untokenize(modified_tokens)
            path.write_bytes(fixed_source)
            result["fixed"] = True
    except Exception as exc:
        result["messages"].append(f"Error while fixing: {exc}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively scan and optionally fix Python files containing invalid escape sequences."
        )
    )
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help=(
            "Automatically fix invalid escape sequences by converting affected string literals to raw strings."
        ),
    )
    args = parser.parse_args()
    root = Path.cwd()
    issues_count = 0
    fixed_count = 0
    for path in walk_python_files(root):
        print(f"Processing {path}")
        result = process_file(path, auto_fix=args.auto_fix)
        if not result["has_issues"]:
            continue
        issues_count += 1
        status = "[FIXED]" if result["fixed"] else "[ISSUE]"
        print(f"{status} {path}")
        for message in result["messages"]:
            print(f"  -> {message}")
        if result["fixed"]:
            fixed_count += 1
    print("=" * 40)
    print("Summary:")
    print(f"  Files with invalid escape sequences: {issues_count}")
    if args.auto_fix:
        print(f"  Files successfully auto-fixed:      {fixed_count}")


if __name__ == "__main__":
    raise SystemExit(main())
