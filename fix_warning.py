#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

INVALID_ESCAPE_RE = re.compile(r"\\(?![\\\'\"abfnrtv0-7xuUNN])")


def has_invalid_escape(s: str) -> bool:
    return bool(INVALID_ESCAPE_RE.search(s))


def make_raw_string(source: str) -> str:
    m = re.match(
        r"^([rubfRUBF]*)?(?P<quote>\"\"\"|\'\'\'|\"|\')(?P<body>.*)(?P=quote)$",
        source,
        re.DOTALL,
    )
    if not m:
        return source
    prefix = m.group(1) or ""
    quote = m.group("quote")
    body = m.group("body")
    if "r" in prefix.lower():
        return source
    if body.endswith("\\") and not body.endswith("\\\\"):
        return source
    if quote == '"' and '"' in body and '"""' not in source:
        return source
    if quote == "'" and "'" in body and "'''" not in source:
        return source
    new_prefix = prefix + ("r" if "r" not in prefix.lower() else "")
    return f"{new_prefix}{quote}{body}{quote}"


def fix_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    changed = False
    out_tokens = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError:
        return False
    for tok in tokens:
        if tok.type == tokenize.STRING and has_invalid_escape(tok.string):
            fixed = make_raw_string(tok.string)
            if fixed != tok.string:
                tok = tokenize.TokenInfo(tok.type, fixed, tok.start, tok.end, tok.line)
                changed = True
        out_tokens.append(tok)
    if changed:
        new_text = tokenize.untokenize(out_tokens)
        path.write_text(new_text, encoding="utf-8")
    return changed


def scan_and_fix(cwd: str):
    root = Path(cwd)
    fixed_files = []
    for path in root.rglob("*.py"):
        if fix_file(path):
            fixed_files.append(str(path))
    return fixed_files


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_invalid_escapes.py <directory>")
        sys.exit(1)
    directory = sys.argv[1]
    fixed = scan_and_fix(directory)
    if fixed:
        print("Fixed files:")
        for f in fixed:
            print(" -", f)
    else:
        print("No files needed fixing.")
