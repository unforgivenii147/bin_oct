#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from dh import get_files, mpf3


def fix_print_statements_manually(content: str):
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if re.search("\\bprint\\s+", line) and (not is_in_string(line, "print")):
            if ">>" in line:
                line = re.sub(
                    "print\\s+>>\\s*(\\w+)\\s*,\\s*(.+?)(?:\\s*#.*)?$",
                    "print(\\2, file=\\1)",
                    line,
                )
            else:
                line = re.sub("print\\s+(.+?)(?:\\s*#.*)?$", "print(\\1)", line)
            new_lines.append(line)
        else:
            new_lines.append(line)
    return "\n".join(new_lines)


def is_in_string(line: str, text: str) -> bool:
    in_string = False
    quote_char = None
    for i, char in enumerate(line):
        if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
            if not in_string:
                in_string = True
                quote_char = char
            elif char == quote_char:
                in_string = False
                quote_char = None
        elif in_string and text in line[i - len(text) : i + 1]:
            return True
    return False


def process_file(path: str | Path) -> bool:
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        fixed_content = fix_print_statements_manually(content)
        if fixed_content != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(fixed_content)
            print("  ✅ Manual conversion applied")
            result = subprocess.run(
                ["ruff", "check", "--fix", "--select", "UP010", path],
                capture_output=True,
                text=True,
            )
            if not result.returncode:
                print("  ✅ Ruff applied additional fixes")
                return True
            else:
                print(f"  📝 Would convert {path}")
                return True
        else:
            print(f"  ⚠️  Could not automatically convert {path}")
            return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
