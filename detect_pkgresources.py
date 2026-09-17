#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from multiprocessing import Pool
from pathlib import Path

REPLACEMENTS = {
    (
        r"pkg_resources\.resource_filename\(",
        "importlib.resources.files(",
    ),
    (
        r"pkg_resources\.resource_string\(",
        "importlib.resources.files(",
    ),
    (
        r"pkg_resources\.require\(",
        "packaging.requirements.Requirement(",
    ),
    (
        r"pkg_resources\.get_distribution\(",
        "importlib.metadata.version(",
    ),
    (
        r"pkg_resources\.iter_entry_points\(",
        "importlib.metadata.entry_points(",
    ),
    (
        r"pkg_resources\.parse_version\(",
        "packaging.version.Version(",
    ),
}


def detect_pkg_resources(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return {"file": path, "error": str(e), "found": False}
    has_import = re.search(
        r"^import\s+pkg_resources|^from\s+pkg_resources", content, re.MULTILINE
    )
    if not has_import:
        return {"file": path, "found": False}
    usages = []
    for pattern, _ in REPLACEMENTS:
        matches = re.finditer(pattern, content)
        for match in matches:
            line_num = content[: match.start()].count("\n") + 1
            usages.append({"pattern": pattern, "line": line_num})
    result = {
        "file": path,
        "found": bool(usages),
        "usages": usages,
        "imports_needed": set(),
    }
    if has_import:
        if re.search(r"pkg_resources\.resource_filename", content):
            result["imports_needed"].add("importlib.resources")
        if re.search(r"pkg_resources\.resource_string", content):
            result["imports_needed"].add("importlib.resources")
        if re.search(r"pkg_resources\.require", content):
            result["imports_needed"].add("packaging.requirements")
        if re.search(r"pkg_resources\.get_distribution", content):
            result["imports_needed"].add("importlib.metadata")
        if re.search(r"pkg_resources\.iter_entry_points", content):
            result["imports_needed"].add("importlib.metadata")
        if re.search(r"pkg_resources\.parse_version", content):
            result["imports_needed"].add("packaging.version")
    result["imports_needed"] = sorted(result["imports_needed"])
    return result


def autofix_pkg_resources(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return {"file": path, "error": str(e), "fixed": False}
    original_content = content
    content = re.sub(
        r"^import\s+pkg_resources\n|^from\s+pkg_resources.*\n",
        "",
        content,
        flags=re.MULTILINE,
    )
    imports_needed = set()
    for old_pattern, new_pattern in REPLACEMENTS:
        if re.search(old_pattern, content):
            content = re.sub(old_pattern, new_pattern, content)
            if "importlib.resources" in new_pattern:
                imports_needed.add("importlib.resources")
            elif "packaging.requirements" in new_pattern:
                imports_needed.add("packaging.requirements")
            elif "importlib.metadata" in new_pattern:
                imports_needed.add("importlib.metadata")
            elif "packaging.version" in new_pattern:
                imports_needed.add("packaging.version")
    if imports_needed:
        import_lines = "\n".join(f"import {imp}" for imp in sorted(imports_needed))
        match = re.search(
            r"^(#!.*\n)?(\"\"\".*?\"\"\"\n)?", content, re.MULTILINE | re.DOTALL
        )
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + import_lines + "\n" + content[insert_pos:]
        else:
            content = import_lines + "\n" + content
    if content != original_content:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "file": path,
                "fixed": True,
                "imports_added": sorted(imports_needed),
            }
        except OSError as e:
            return {"file": path, "error": f"Write failed: {e}", "fixed": False}
    return {"file": path, "fixed": False, "reason": "No changes needed"}


def collect_python_files(paths: list[str]) -> list[Path]:
    py_files = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
    return sorted(set(py_files))


def main():
    parser = argparse.ArgumentParser(
        description="Detect and autofix deprecated pkg_resources usage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python script.py
  python script.py -a
  python script.py src/ -a
  python script.py file.py
  python script.py file1.py file2.py
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Python files or directories to process (default: . recursively)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Autofix pkg_resources usage (replace with importlib/packaging)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=4,
        help="Number of parallel processes (default: 4)",
    )
    args = parser.parse_args()
    paths = args.paths if args.paths else ["."]
    py_files = collect_python_files(paths)
    if not py_files:
        print("No .py files found.")
        return
    print(
        f"Found {len(py_files)} file(s) | Mode: {'AUTOFIX' if args.autofix else 'REPORT'}"
    )
    print()
    try:
        if args.autofix:
            with Pool(processes=args.jobs) as pool:
                results = pool.map(autofix_pkg_resources, py_files)
            fixed_count = 0
            for result in results:
                if result.get("error"):
                    print(f"❌ {result['file']}: {result['error']}")
                elif result.get("fixed"):
                    fixed_count += 1
                    imports = ", ".join(result.get("imports_added", []))
                    print(f"✓ {result['file']} | Added: {imports}")
                else:
                    reason = result.get("reason", "No pkg_resources found")
                    if reason != "No pkg_resources found":
                        print(f"- {result['file']}: {reason}")
            print()
            print(f"Fixed {fixed_count}/{len(py_files)} file(s)")
        else:
            with Pool(processes=args.jobs) as pool:
                results = pool.map(detect_pkg_resources, py_files)
            found_count = 0
            for result in results:
                if result.get("error"):
                    print(f"❌ {result['file']}: {result['error']}")
                elif result.get("found"):
                    found_count += 1
                    usages = result.get("usages", [])
                    imports = ", ".join(result.get("imports_needed", []))
                    print(f"⚠ {result['file']}")
                    for usage in usages:
                        print(f"   Line {usage['line']}: {usage['pattern']}")
                    print(f"   Imports: {imports}\n")
            print()
            print(f"Found pkg_resources in {found_count}/{len(py_files)} file(s)")
            if found_count > 0:
                print("Run with -a to autofix.")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
