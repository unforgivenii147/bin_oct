#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def replace_in_file(path: Path, old_text: str, new_text: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if old_text not in content:
            return False
        new_content = content.replace(old_text, new_text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Error processing {path}: {e}")
        return False


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python replacer.py <old_text> <new_text>")
        print("\nExample:")
        print(
            'python replacer.py "    try:\\n    path=Path(path)" "    path=Path(path)\\n    try:"'
        )
        sys.exit(1)
    old_text = sys.argv[1]
    new_text = sys.argv[2]
    old_text = old_text.encode().decode("unicode_escape")
    new_text = new_text.encode().decode("unicode_escape")
    cwd = Path(".")
    py_files = list(cwd.glob("*.py"))
    if not py_files:
        print("No Python files found in current directory.")
        sys.exit(0)
    print(f"Found {len(py_files)} Python file(s)")
    print(f"Replacing: {old_text!r}")
    print(f"With:      {new_text!r}")
    print("-" * 40)
    modified_count = 0
    for py_file in py_files:
        if replace_in_file(py_file, old_text, new_text):
            print(f"✓ Modified: {py_file}")
            modified_count += 1
        else:
            print(f"  Skipped: {py_file} (no match)")
    print("-" * 40)
    print(f"Done! Modified {modified_count} file(s).")


if __name__ == "__main__":
    raise SystemExit(main())
_
