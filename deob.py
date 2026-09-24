#!/data/data/com.termux/files/home/.local/bin/python
"""
deobfuscate.py — Convert variable-stuffed / eval-based bash scripts
into readable, deobfuscated bash.

Usage:
    python3 deobfuscate.py <input.sh> [-o <output.sh>]

If -o/--output is omitted, the output path is derived from the input:
    input.sh   -> input.deobf.sh
    script     -> script.deobf.sh
    script.sh  -> script.deobf.sh
Existing files are never overwritten: .1, .2, … suffixes are appended.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ----------------------------------------------------------------------
# 1. Extract every NAME='...' / NAME="..." assignment in the file
# ----------------------------------------------------------------------
_ASSIGN_RE = re.compile(
    r"""
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)=
    (?:
        '(?P<single>[^']*)'             # single-quoted value
      | "(?P<double>(?:[^"\\]|\\.)*)"   # double-quoted value (with escapes)
    )
    """,
    re.VERBOSE | re.DOTALL,
)


def parse_assignments(src: str) -> dict[str, str]:
    """Return {varname: value} for every assignment found in src."""
    out: dict[str, str] = {}
    for m in _ASSIGN_RE.finditer(src):
        name = m.group("name")
        if m.group("single") is not None:
            out[name] = m.group("single")
        else:
            # Unescape the sequences bash understands inside "..."
            out[name] = re.sub(r"\\([\"\\$`])", r"\1", m.group("double"))
    return out


# ----------------------------------------------------------------------
# 2. Find the eval "..." expression
# ----------------------------------------------------------------------
_EVAL_RE = re.compile(r'\beval\s+"((?:[^"\\]|\\.)*)"')


def find_eval_expr(src: str) -> str | None:
    m = _EVAL_RE.search(src)
    return m.group(1) if m else None


# ----------------------------------------------------------------------
# 3. Replace $Var and ${Var} with their values
# ----------------------------------------------------------------------
def substitute(expr: str, variables: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        return variables.get(name, m.group(0))  # leave unknown vars alone

    expr = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, expr)
    expr = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", repl, expr)
    return expr


# ----------------------------------------------------------------------
# 4. Light cosmetic pass — split on obvious statement boundaries
# ----------------------------------------------------------------------
def pretty(code: str) -> str:
    # Put each `;clear;` on its own line (very common pattern)
    code = code.replace(";clear;", ";\nclear;")
    # Put each `};` that closes a req()-style function on a newline
    code = code.replace(";\n}", ";\n}\n")
    return code


# ----------------------------------------------------------------------
# 5. Output path helper — never overwrite an existing file
# ----------------------------------------------------------------------
def pick_output(inp: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)

    # Build "<stem>.deobf<suffix>", falling back to "<name>.deobf.sh"
    suffix = inp.suffix or ".sh"
    candidate = inp.with_name(f"{inp.stem}.deobf{suffix}")
    if candidate == inp:
        candidate = inp.with_name(f"{inp.name}.deobf.sh")

    # If it already exists, append .1 .2 .3 ...
    base = candidate
    n = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.stem}.{n}{base.suffix}")
        n += 1
    return candidate


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("input", help="obfuscated bash file")
    ap.add_argument("-o", "--output", help="output path (optional)")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.is_file():
        print(f"error: {inp}: not a file", file=sys.stderr)
        return 1

    src = inp.read_text(encoding="utf-8", errors="replace")

    variables = parse_assignments(src)
    expr = find_eval_expr(src)
    if expr is None:
        print('error: no eval "…" expression found', file=sys.stderr)
        return 1

    resolved = substitute(expr, variables)
    resolved = pretty(resolved)

    out = pick_output(inp, args.output)
    out.write_text(resolved.rstrip() + "\n", encoding="utf-8")
    print(f"[+] wrote {out}  ({len(resolved.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
