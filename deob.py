#!/data/data/com.termux/files/home/.local/bin/python
"""
deob.py - Static deobfuscator for common bash obfuscation styles.

Targets:
  * eval "<concatenation of $a$b$c...>" with one-letter var names
  * printf / echo -e  hex / octal escape reconstruction
  * base64 -d  (here-string, heredoc, and pipe forms)
  * tr  character-class mapping (incl. ROT13-style rotations)
  * rev  (string reversal)
  * nested evals up to MAX_PASSES
  * bash ANSI-C quoting  $'\\x41'
  * single/double quote re-quoting when splicing strings

It performs *no* execution: everything is a pure textual rewrite.
That is a hard design rule -- a deobfuscator that runs its input has
already lost.

Usage:
    python3 deob.py file1.sh file2.sh ...
    python3 deob.py -o out.sh in.sh
    python3 deob.py --stdout in.sh       # print, don't write

Output (default): <input>.deob.sh next to the input.

Exit codes:
    0  all inputs processed (even if output identical to input)
    1  at least one input failed
    2  bad arguments
"""

from __future__ import annotations

import argparse
import base64
import binascii
import re
import string
import sys
from pathlib import Path


# ===========================================================================
# Tunables
# ===========================================================================
OUTPUT_SUFFIX = ".deob.sh"  # appended to input name
MAX_PASSES = 25  # unwrap nested eval / pipeline layers
MAX_EXPAND = 80  # recursive var-substitution depth cap


# ===========================================================================
# 1. Small string utilities
# ===========================================================================

_DQ_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    '"': '"',
    "$": "$",
    "`": "`",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
}


def unescape_dq(s: str) -> str:
    """Turn the inside of a double-quoted bash string into raw text."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_DQ_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


_HEX = set(string.hexdigits)
_OCT = set("01234567")


def unescape_ansi_c(s: str) -> str:
    """
    Decode the body of a bash ANSI-C string  $'...'  into raw bytes.

    Supports \\xHH, \\uHHHH, \\UHHHHHHHH, \\nnn (octal), \\n \\t \\r etc.
    Unknown escapes pass through unchanged so we never corrupt input.
    """
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue

        # We saw a backslash. Look at the next char.
        i += 1
        if i >= n:
            out.append("\\")
            break
        e = s[i]

        if e == "x":
            i += 1
            j = i
            while j < n and s[j] in _HEX and j - i < 2:
                j += 1
            if j > i:
                out.append(chr(int(s[i:j], 16)))
                i = j
            else:
                out.append("\\x")
            continue

        if e == "u":
            i += 1
            j = i
            while j < n and s[j] in _HEX and j - i < 4:
                j += 1
            if j > i:
                out.append(chr(int(s[i:j], 16)))
                i = j
            else:
                out.append("\\u")
            continue

        if e == "U":
            i += 1
            j = i
            while j < n and s[j] in _HEX and j - i < 8:
                j += 1
            if j > i:
                cp = int(s[i:j], 16)
                try:
                    out.append(chr(cp))
                except ValueError:
                    out.append("\\U" + s[i:j])
                i = j
            else:
                out.append("\\U")
            continue

        if e in _OCT:
            j = i
            while j < n and s[j] in _OCT and j - i < 3:
                j += 1
            out.append(chr(int(s[i:j], 8)))
            i = j
            continue

        # named single-char escape
        out.append(_DQ_ESCAPES.get(e, "\\" + e))
        i += 1

    return "".join(out)


# ===========================================================================
# 2. Variable-assignment extraction
# ===========================================================================

# Single-line:  NAME='value'  /  NAME="value"  /  NAME=$'value'
# We anchor at line start (optional whitespace) so we don't match inside
# other constructs. RHS is non-greedy up to the matching quote.
_ASSIGN_RE = re.compile(
    r"""^[ \t]*
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        =
        (?:
            \$'(?P<ansi>(?:\\.|[^'\\])*)'   # $'...'  ANSI-C
          |  '(?P<sq>[^']*)'                # '...'   literal
          |  "(?P<dq>(?:\\.|[^"\\])*)"      # "..."   with escapes
        )
        [ \t]*;?[ \t]*$
    """,
    re.VERBOSE | re.MULTILINE,
)


def extract_assignments(text: str) -> dict[str, str]:
    """
    Return {NAME: raw_value} for every simple quoted assignment.
    $'...' is decoded to raw bytes; "..." is escape-decoded; '...' is literal.
    """
    table: dict[str, str] = {}
    for m in _ASSIGN_RE.finditer(text):
        if m.group("ansi") is not None:
            table[m.group("name")] = unescape_ansi_c(m.group("ansi"))
        elif m.group("dq") is not None:
            table[m.group("name")] = unescape_dq(m.group("dq"))
        else:
            table[m.group("name")] = m.group("sq")
    return table


# ===========================================================================
# 3. Variable expansion (recursive)
# ===========================================================================

_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def expand_vars(expr: str, table: dict[str, str], depth: int = 0) -> str:
    """
    Repeatedly substitute $name / ${name} from `table` until fixpoint.
    Unknown names are left alone (never lose information).
    """
    if depth > MAX_EXPAND:
        return expr

    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        name = m.group(1)
        if name in table:
            changed = True
            return table[name]
        return m.group(0)

    new = _VAR_REF_RE.sub(repl, expr)
    if changed and new != expr:
        return expand_vars(new, table, depth + 1)
    return new


# ===========================================================================
# 4. Top-level eval detection
# ===========================================================================

# eval "..."  |  eval '...'  |  eval $var...   (unquoted bare var expression)
_EVAL_RE = re.compile(
    r"""\beval\s+
        (?:
            "(?P<dq>(?:\\.|[^"\\])*)"
          | '(?P<sq>[^']*)'
          | (?P<bare>\$[^\n;|&]+)
        )
    """,
    re.VERBOSE,
)


def find_eval_payload(text: str) -> str | None:
    """Return the argument text of the first eval (unquoted)."""
    m = _EVAL_RE.search(text)
    if not m:
        return None
    if m.group("dq") is not None:
        return unescape_dq(m.group("dq"))
    if m.group("sq") is not None:
        return m.group("sq")
    return m.group("bare")


# ===========================================================================
# 5. Stage decoders:  printf / echo -e / base64 / tr / rev
# ===========================================================================

# --- 5a. printf with a literal format string -------------------------------
# printf '\x41\x42'      printf '%b' '\x41'      printf '\101'
# We only handle cases where every argument is a literal string; anything
# dynamic ($var unresolved) is skipped.
_PRINTF_RE = re.compile(
    r"""\bprintf\s+
        (?P<fmt>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
        (?P<args>(?:\s+(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"))*)
    """,
    re.VERBOSE,
)

_STR_LIT_RE = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"")


def _decode_printf(fmt: str, args: list[str]) -> str | None:
    """
    Very small printf(1) emulator: supports %b (interpret escapes in arg),
    %s (substitute literal), and %% plus passthrough literals in fmt.
    Returns None if fmt contains unsupported conversions like %d.
    """
    out: list[str] = []
    fi = 0
    ai = 0
    n = len(fmt)

    while fi < n:
        c = fmt[fi]
        if c != "%":
            out.append(c)
            fi += 1
            continue

        if fi + 1 >= n:
            out.append("%")
            break
        conv = fmt[fi + 1]
        fi += 2

        if conv == "%":
            out.append("%")
            continue

        if conv in ("b", "s"):
            if ai >= len(args):
                return None
            a = args[ai]
            ai += 1
            if conv == "b":
                out.append(unescape_ansi_c(a))
            else:
                out.append(a)
            continue

        # Unsupported conversion (%d, %x, ...) -> give up on this call
        return None

    return "".join(out)


def try_decode_printf(text: str) -> tuple[str, bool]:
    """Replace every statically-evaluable printf with its output."""
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        raw_fmt = m.group("fmt")
        # unquote fmt
        if raw_fmt.startswith("'"):
            fmt = raw_fmt[1:-1]
        else:
            fmt = unescape_dq(raw_fmt[1:-1])
        fmt = unescape_ansi_c(fmt)  # printf interprets escapes in fmt too

        # split args into raw strings
        args: list[str] = []
        for sm in _STR_LIT_RE.finditer(m.group("args") or ""):
            if sm.group(1) is not None:
                args.append(sm.group(1))
            else:
                args.append(unescape_dq(sm.group(2)))

        # if any arg contains a variable ref that wasn't expanded, skip
        if any("$" in a for a in args):
            return m.group(0)

        decoded = _decode_printf(fmt, args)
        if decoded is None:
            return m.group(0)

        changed = True
        return decoded

    return _PRINTF_RE.sub(repl, text), changed


# --- 5b. echo -e '\x41' ---------------------------------------------------
_ECHO_E_RE = re.compile(
    r"""\becho\s+-e\s+
        (?P<s>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
    """,
    re.VERBOSE,
)


def try_decode_echo_e(text: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        raw = m.group("s")
        if raw.startswith("'"):
            body = raw[1:-1]
        else:
            body = unescape_dq(raw[1:-1])
        changed = True
        return unescape_ansi_c(body)

    return _ECHO_E_RE.sub(repl, text), changed


# --- 5c. base64 -d --------------------------------------------------------
# Three common forms:
#   echo "PAYLOAD" | base64 -d
#   base64 -d <<< "PAYLOAD"
#   base64 -d <<EOF
#   PAYLOAD
#   EOF
_B64_PIPE_RE = re.compile(
    r"""echo\s+(?P<q>['"])(?P<data>[A-Za-z0-9+/=\s]*?)(?P=q)
        \s*\|\s*
        base64\s+(?:-[dD]|--decode)
    """,
    re.VERBOSE | re.DOTALL,
)

_B64_HERESTR_RE = re.compile(
    r"""base64\s+(?:-[dD]|--decode)\s*<<<\s*
        (?P<q>['"])(?P<data>[A-Za-z0-9+/=\s]*?)(?P=q)
    """,
    re.VERBOSE | re.DOTALL,
)

_B64_HEREDOC_RE = re.compile(
    r"""base64\s+(?:-[dD]|--decode)\s*<<\s*(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\s*\n
        (?P<data>.*?)\n
        (?P=tag)\b
    """,
    re.VERBOSE | re.DOTALL,
)


def _b64_try(s: str) -> str | None:
    """Attempt a lenient base64 decode; return None on failure."""
    try:
        # tolerate whitespace / missing padding
        cleaned = re.sub(r"\s+", "", s)
        cleaned += "=" * (-len(cleaned) % 4)
        return base64.b64decode(cleaned, validate=True).decode(
            "utf-8", errors="replace"
        )
    except (binascii.Error, ValueError):
        return None


def try_decode_base64(text: str) -> tuple[str, bool]:
    changed = False

    def repl_pipe(m: re.Match) -> str:
        nonlocal changed
        dec = _b64_try(m.group("data"))
        if dec is None:
            return m.group(0)
        changed = True
        return dec

    def repl_here(m: re.Match) -> str:
        nonlocal changed
        dec = _b64_try(m.group("data"))
        if dec is None:
            return m.group(0)
        changed = True
        return dec

    def repl_heredoc(m: re.Match) -> str:
        nonlocal changed
        dec = _b64_try(m.group("data"))
        if dec is None:
            return m.group(0)
        changed = True
        return dec

    text = _B64_PIPE_RE.sub(repl_pipe, text)
    text = _B64_HERESTR_RE.sub(repl_here, text)
    text = _B64_HEREDOC_RE.sub(repl_heredoc, text)
    return text, changed


# --- 5d. tr  (character class mapping) ------------------------------------
# Handles:  tr 'a-z' 'n-za-m'      tr 'A-Za-z' 'N-ZA-Mn-za-m'
# and literal one-to-one:   tr 'abc' 'xyz'
_TR_TR_RE = re.compile(
    r"""tr\s+
        (?P<s1>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
        \s+
        (?P<s2>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
    """,
    re.VERBOSE,
)


def _tr_expand_class(spec: str) -> list[str]:
    """
    Expand a tr SET string like 'a-z' or 'A-Z0-9' into a list of chars.
    A leading literal '-' is preserved. Unknown ranges are skipped.
    """
    chars: list[str] = []
    i = 0
    while i < len(spec):
        c = spec[i]
        if i + 2 < len(spec) and spec[i + 1] == "-":
            lo, hi = spec[i], spec[i + 2]
            if ord(lo) <= ord(hi):
                chars.extend(chr(x) for x in range(ord(lo), ord(hi) + 1))
                i += 3
                continue
        chars.append(c)
        i += 1
    return chars


def try_decode_tr(text: str) -> tuple[str, bool]:
    """
    Apply tr to the immediately preceding literal string in a pipe.
    We look for:  'LITERAL' | tr 'X' 'Y'
    """
    pattern = re.compile(
        r"""(?P<q>['"])(?P<lit>(?:\\.|[^'"\\])*)(?P=q)
            \s*\|\s*
            tr\s+
            (?P<s1>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
            \s+
            (?P<s2>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
        """,
        re.VERBOSE,
    )
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        lit = m.group("lit")
        if m.group("q") == '"':
            lit = unescape_dq(lit)

        s1raw = m.group("s1")[1:-1]
        s2raw = m.group("s2")[1:-1]

        set1 = _tr_expand_class(s1raw)
        set2 = _tr_expand_class(s2raw)
        if not set1 or not set2:
            return m.group(0)

        # tr pads set2 with its last char to match set1's length
        if len(set2) < len(set1):
            set2 = set2 + [set2[-1]] * (len(set1) - len(set2))

        mapping = dict(zip(set1, set2))
        result = "".join(mapping.get(ch, ch) for ch in lit)

        changed = True
        # Emit as a single-quoted literal so downstream stages can consume it.
        escaped = result.replace("'", "'\\''")
        return "'" + escaped + "'"

    return pattern.sub(repl, text), changed


# --- 5e. rev ---------------------------------------------------------------
_REV_RE = re.compile(r"""(?P<q>['"])(?P<lit>(?:\\.|[^'"\\])*)(?P=q)\s*\|\s*rev\b""")


def try_decode_rev(text: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        lit = m.group("lit")
        if m.group("q") == '"':
            lit = unescape_dq(lit)
        changed = True
        escaped = lit[::-1].replace("'", "'\\''")
        return "'" + escaped + "'"

    return _REV_RE.sub(repl, text), changed


# ===========================================================================
# 6. One deobfuscation pass
# ===========================================================================


def deobfuscate_once(text: str) -> tuple[str, bool]:
    """
    Apply a single round of every transform. Returns (new_text, progress).
    """
    progress = False

    # -- 6a. static pipeline stage decoders (before eval handling so the
    #        eval payload we splice in is already decoded when possible) --
    for fn in (
        try_decode_printf,
        try_decode_echo_e,
        try_decode_base64,
        try_decode_tr,
        try_decode_rev,
    ):
        text, ch = fn(text)
        progress |= ch

    # -- 6b. assignment table + eval splice --
    table = extract_assignments(text)
    payload = find_eval_payload(text)

    if payload is not None and table:
        # Expand $var refs inside the eval argument. This is the single
        # most important step for the style in the user's sample.
        expanded = expand_vars(payload, table)

        # Only treat as progress if the expansion actually changed
        # something -- otherwise we loop forever on `eval "$x"` where $x
        # isn't in our table.
        if expanded != payload:
            # Remove the giant eval + assignment block and replace with the
            # reconstructed script. We keep any *other* text (functions,
            # shebang, comments) by surgically cutting only lines that
            # participated in the obfuscation.
            # Simple, safe heuristic: replace the eval line with the
            # expanded payload, leave everything else in place. Then let
            # the next pass re-scan.
            def repl(m: re.Match) -> str:
                return expanded

            new_text, n = _EVAL_RE.subn(repl, text, count=1)
            if n:
                text = new_text
                progress = True

    return text, progress


# ===========================================================================
# 7. Multi-pass driver
# ===========================================================================


def deobfuscate(text: str) -> str:
    """Repeatedly apply deobfuscate_once until fixpoint or MAX_PASSES."""
    for _ in range(MAX_PASSES):
        text, progress = deobfuscate_once(text)
        if not progress:
            break
    return text


# ===========================================================================
# 8. CLI
# ===========================================================================


def default_output_path(inp: Path) -> Path:
    """
    inp.sh        -> inp.sh.deob.sh
    inp           -> inp.deob.sh
    """
    return inp.with_name(inp.name + OUTPUT_SUFFIX)


def process_file(inp: Path, out: Path | None, to_stdout: bool = False) -> int:
    """Return 0 on success, 1 on failure. Never raises for I/O errors."""
    try:
        src = inp.read_text(errors="replace")
    except OSError as e:
        print(f"error: cannot read {inp}: {e}", file=sys.stderr)
        return 1

    try:
        result = deobfuscate(src)
    except Exception as e:
        # Defensive: a deobfuscator must never crash on input
        print(f"error: deobfuscation failed for {inp}: {e}", file=sys.stderr)
        return 1

    if to_stdout:
        sys.stdout.write(result)
        return 0

    dest = out or default_output_path(inp)
    try:
        dest.write_text(result)
    except OSError as e:
        print(f"error: cannot write {dest}: {e}", file=sys.stderr)
        return 1

    print(f"  {inp}  ->  {dest}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Static deobfuscator for common bash obfuscation styles."
    )
    ap.add_argument("files", nargs="+", type=Path, help="obfuscated shell script(s)")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output path (only with a single input)",
    )
    ap.add_argument(
        "--stdout",
        action="store_true",
        help="print result to stdout instead of writing a file",
    )
    args = ap.parse_args(argv[1:])

    if args.output and len(args.files) != 1:
        print("error: -o requires exactly one input file", file=sys.stderr)
        return 2
    if args.output and args.stdout:
        print("error: -o and --stdout are mutually exclusive", file=sys.stderr)
        return 2

    rc = 0
    for f in args.files:
        if not f.is_file():
            print(f"skip: {f} (not a file)", file=sys.stderr)
            rc = 1
            continue
        rc |= process_file(f, args.output, to_stdout=args.stdout)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
