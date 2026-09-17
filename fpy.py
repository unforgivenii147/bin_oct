#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

python_keywords = {
    "def",
    "class",
    "import",
    "from",
    "lambda",
    "yield",
    "async",
    "await",
}


def is_probably_python(lines: str) -> bool:
    score = 0
    for line in lines:
        if any(kw in line for kw in python_keywords):
            score += 1
        if re.search(r":\s*$", line):
            score += 1
        if re.match(r"\s{4}", line):
            score += 1
    return score >= 2


def looks_like_python(code_block: str) -> bool | None:
    try:
        tokenize.generate_tokens(StringIO(code_block).readline)
        return True
    except tokenize.TokenError:
        return False


def is_python_like(line: str) -> bool:
    if re.match(r"\s*(def|class|if|elif|else|for|while|try|except|with)\b.*:", line):
        return True
    if re.match(r"\s*@[A-Za-z_]\w*", line):
        return True
    return bool(re.match(r"\s*import\b|\s*from\b", line))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fpy.py <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    try:
        with Path(fname).open(encoding="utf-8") as f:
            lines = f.readlines()
        filtered = [
            line
            for line in lines
            if is_python_like(line)
            or looks_like_python(line)
            or is_probably_python(line)
        ]
        print(filtered)
        with Path("out.py").open("w", encoding="utf-8") as f:
            for l in filtered:
                f.write(l)
                f.write("\n")
    except FileNotFoundError:
        print(f"Error: File '{fname}' not found.")
    except Exception as e:
        print("An error occurred:", e)
