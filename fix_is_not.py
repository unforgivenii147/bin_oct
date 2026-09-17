#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import concurrent.futures
import os
import tokenize
from pathlib import Path


def process_file(path: Path, auto_fix: bool = False) -> dict:
    result = {
        "path": path,
        "found_count": 0,
        "fixed": False,
        "lines": [],
        "error": None,
    }
    try:
        with path.open("rb") as f:
            tokens = list(tokenize.tokenize(f.readline))
    except Exception as e:
        result["error"] = f"Failed to read/tokenize: {e}"
        return result
    modified_tokens = []
    i = 0
    n = len(tokens)
    is_modified = False
    while i < n:
        tok = tokens[i]
        if (
            i + 1 < n
            and tok.type == tokenize.NAME
            and tok.string == "is"
            and tokens[i + 1].type == tokenize.NAME
            and tokens[i + 1].string == "not"
        ):
            result["found_count"] += 1
            result["lines"].append(tok.start[0])
            if auto_fix:
                new_tok = tok._replace(type=tokenize.OP, string="!=")
                modified_tokens.append(new_tok)
                i += 2
                is_modified = True
                continue
        modified_tokens.append(tok)
        i += 1
    if is_modified and auto_fix:
        try:
            fixed_bytes = tokenize.untokenize(modified_tokens)
            path.write_bytes(fixed_bytes)
            result["fixed"] = True
        except Exception as e:
            result["error"] = f"Failed to write auto-fix: {e}"
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Recursively find and optionally replace 'is not' with '!=' in Python files."
    )
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically replace 'is not' with '!=' across files.",
    )
    args = parser.parse_args()
    current_dir = Path(".")
    py_files = list(current_dir.rglob("*.py"))
    script_path = Path(__file__).resolve()
    py_files = [f for f in py_files if f.resolve() != script_path]
    if not py_files:
        print("🔍 No Python files found to scan.")
        return
    cpu_cores = os.cpu_count() or 1
    print(f"🔍 Found {len(py_files)} Python files.")
    print(f"⚡ Processing concurrently across {cpu_cores} parallel workers...")
    if args.auto_fix:
        print(
            "🛠️  Auto-fix mode active (-a). 'is not' operators will be converted to '!='."
        )
    print("-" * 40)
    total_files_with_issues = 0
    total_replacements = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=cpu_cores) as executor:
        futures = {executor.submit(process_file, f, args.auto_fix): f for f in py_files}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res["error"]:
                print(f"❌ [ERROR] {res['path']}: {res['error']}")
                continue
            if res["found_count"] > 0:
                total_files_with_issues += 1
                total_replacements += res["found_count"]
                status = "[🔧 FIXED]" if res["fixed"] else "[⚠️  FOUND]"
                lines_str = ", ".join(map(str, res["lines"]))
                print(
                    f"{status} {res['path']} -> Found {res['found_count']} time(s) on line(s): {lines_str}"
                )
    print("-" * 40)
    print("📊 Summary:")
    print(f"   Files containing 'is not': {total_files_with_issues}")
    print(f"   Total instances found:     {total_replacements}")


if __name__ == "__main__":
    raise SystemExit(main())
