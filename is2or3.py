#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import ast
import sys
from pathlib import Path

from dh import get_files


def detect_version(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading file: {e}")
        return
    py2_score = 0
    py3_score = 0
    reasons = []
    try:
        tree = ast.parse(source)
        py3_score += 1
        reasons.append("Parsed successfully with Python 3 syntax.")
    except SyntaxError:
        print(
            f"{path.name}\nConfidence: High\nReason: Syntax error when parsed with Python 3."
        )
        return
    if "print " in source and "print(" not in source:
        py2_score += 2
        reasons.append("Uses print statement without parentheses (Python 2 style).")
    if "__future__" in source and "print_function" in source:
        py3_score += 2
        reasons.append(
            "Uses 'from __future__ import print_function' (Python 3 compatibility)."
        )
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
            py3_score += 3
            reasons.append("Uses async/await syntax (Python 3 only).")
        if isinstance(node, ast.Try) and hasattr(node, "finalbody"):
            py3_score += 1
            reasons.append("Uses try/finally block (Python 3 syntax).")
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.args:
                if hasattr(arg, "annotation") and arg.annotation is not None:
                    py3_score += 2
                    reasons.append(
                        "Uses function argument annotations (Python 3 feature)."
                    )
    if py2_score > py3_score:
        version = "2"
        confidence = "High" if py2_score - py3_score > 2 else "Medium"
    elif py3_score > py2_score:
        version = "3"
        confidence = "High" if py3_score - py2_score > 2 else "Medium"
    else:
        version = "3"
        confidence = "Low"
        reasons.append("No strong indicators found; defaulting to Python 3.")
    if version == "2":
        print(f"{path.name} : {version}\nConfidence: {confidence}\nReason(s):")


if __name__ == "__main__":
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    for path in files:
        detect_version(path)
