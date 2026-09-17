#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

NORMAL_IMPORT = "^import re\\b"
REGEX_IMPORT = r"^import regex as re\b"


def update_file(path, reverse: bool = False) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = []
        changed = False
        search_pat = REGEX_IMPORT if reverse else NORMAL_IMPORT
        replacement = "import re" if reverse else "import regex as re"
        for line in lines:
            if not changed and re.match(search_pat, line):
                new_lines.append(re.sub(search_pat, replacement, line))
                changed = True
            else:
                new_lines.append(line)
        if changed:
            path.write_text("".join(new_lines), encoding="utf-8")
            return f"Updated: {path}"
        return None
    except Exception as e:
        return f"Error processing {path}: {e}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively swap 'import re' with 'import regex as re'"
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Reverse the replacement (regex as re -> re)",
    )
    args = parser.parse_args()
    cwd = Path.cwd()
    py_files = get_pyfiles(cwd)
    print(f"Scanning {len(py_files)} files...")
    with ProcessPoolExecutor() as executor:
        results = list(
            executor.map(update_file, py_files, [args.reverse] * len(py_files))
        )
    updates = [r for r in results if r]
    for msg in updates:
        print(msg)
    print(f"\nTask complete. Files modified: {len(updates)}")


if __name__ == "__main__":
    raise SystemExit(main())
