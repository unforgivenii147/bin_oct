#!/data/data/com.termux/files/home/.local/bin/python
"""
deob.py - Static deobfuscator for common bash obfuscation styles.

Targets:
  * eval "<concatenation of $a$b$c...>" with one-letter var names
  * printf / echo -e hex/octal/ANSI-C escape reconstruction
  * XOR arithmetic with constant key:  $((c ^ K))
  * byte-loop reconstruction:  for i in ...; do printf ...; done
  * multi-stage pipelines:  echo LIT | base64 -d | zcat | xxd -r -p | rev | tr ...
  * single-command here-strings:  base64 -d <<< LIT  /  xxd -r -p <<< LIT  /  zcat <<< LIT
  * nested evals up to MAX_PASSES
  * bash ANSI-C quoting  $'\\x41'
  * single/double quote re-quoting when splicing strings

Design rule: no execution. Every transform is a pure text rewrite.
A deobfuscator that runs its input has already lost.

Usage:
    python3 deob.py file1.sh file2.sh ...
    python3 deob.py -o out.sh in.sh
    python3 deob.py --stdout in.sh
    python3 deob.py --report in.sh      # also writes in.sh.sh.report.txt

Output (default): <input>.sh next to the input.
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import operator as op
import re
import string
import sys
import zlib
from pathlib import Path


# ===========================================================================
# Tunables
# ===========================================================================
OUTPUT_SUFFIX = ".sh"
REPORT_SUFFIX = ".txt"
MAX_PASSES = 30
MAX_EXPAND = 80
MAX_LOOP_BYTES = 4096
MAX_ARITH_LEN = 512


# ===========================================================================
# 1. String utilities
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
    """Inside of a double-quoted bash string -> raw text."""
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
    """Body of a bash ANSI-C string ($'...') -> raw text."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
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
        out.append(_DQ_ESCAPES.get(e, "\\" + e))
        i += 1

    return "".join(out)


def emit_literal(s: str) -> str:
    """
    Emit a Python string as a single-quoted bash literal. Non-printable
    characters are kept raw (single quotes in bash accept any byte except
    NUL). The only character we must escape is the single quote itself.
    """
    return "'" + s.replace("'", "'\\''") + "'"


def _bytes_to_str(raw: bytes) -> str:
    """Decode bytes as UTF-8 when possible, else latin-1 (round-trippable)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _str_to_bytes(s: str) -> bytes | None:
    """Inverse of _bytes_to_str; returns None if the str isn't re-encodable."""
    try:
        return s.encode("latin-1")
    except UnicodeEncodeError:
        try:
            return s.encode("utf-8")
        except UnicodeEncodeError:
            return None


# ===========================================================================
# 2. Variable-assignment extraction
# ===========================================================================

_ASSIGN_RE = re.compile(
    r"""^[ \t]*
        (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        =
        (?:
            \$'(?P<ansi>(?:\\.|[^'\\])*)'
          |  '(?P<sq>[^']*)'
          |  "(?P<dq>(?:\\.|[^"\\])*)"
        )
        [ \t]*;?[ \t]*$
    """,
    re.VERBOSE | re.MULTILINE,
)


def extract_assignments(text: str) -> dict[str, str]:
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
# 2b. Arithmetic constant-folding
# ===========================================================================

_ARITH_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: lambda a, b: a // b,  # bash `/` is integer
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.LShift: op.lshift,
    ast.RShift: op.rshift,
    ast.BitAnd: op.and_,
    ast.BitOr: op.or_,
    ast.BitXor: op.xor,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
    ast.Invert: op.invert,
}


class _ArithEval(ast.NodeVisitor):
    """Evaluate an integer-only arithmetic AST. Raise ValueError otherwise."""

    def visit_Expression(self, n):
        return self.visit(n.body)

    def visit_Constant(self, n):
        if isinstance(n.value, int):
            return n.value
        raise ValueError("non-int constant")

    visit_Num = visit_Constant

    def visit_BinOp(self, n):
        f = _ARITH_OPS.get(type(n.op))
        if f is None:
            raise ValueError("unsupported binop")
        a, b = self.visit(n.left), self.visit(n.right)
        if isinstance(n.op, ast.Pow) and (abs(a) > 32 or abs(b) > 32):
            raise ValueError("exponent too large")
        if isinstance(n.op, (ast.LShift, ast.RShift)) and abs(b) > 64:
            raise ValueError("shift too large")
        return f(a, b)

    def visit_UnaryOp(self, n):
        f = _ARITH_OPS.get(type(n.op))
        if f is None:
            raise ValueError("unsupported unop")
        return f(self.visit(n.operand))

    def generic_visit(self, n):
        raise ValueError(f"unsupported node: {type(n).__name__}")


_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def _substitute_bare_names(expr: str, table: dict[str, str]) -> str | None:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        val = table.get(name)
        if val is None:
            raise KeyError(name)
        try:
            n = int(val, 0)  # handles 0x.. 0b.. 0o.. decimal
        except (ValueError, TypeError):
            raise KeyError(name)
        return str(n)

    try:
        return _IDENT_RE.sub(repl, expr)
    except KeyError:
        return None


def eval_arith(expr: str, table: dict[str, str]) -> int | None:
    if len(expr) > MAX_ARITH_LEN:
        return None
    if any(ch in expr for ch in "$`;&|<>"):
        return None
    with_ints = _substitute_bare_names(expr, table)
    if with_ints is None or "$" in with_ints:
        return None
    try:
        tree = ast.parse(with_ints, mode="eval")
    except SyntaxError:
        return None
    try:
        return _ArithEval().visit(tree)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


_ARITH_REF_RE = re.compile(r"\$\(\(\s*(?P<expr>[^()]*?)\s*\)\)")


def fold_arith(text: str, table: dict[str, str]) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        val = eval_arith(m.group("expr"), table)
        if val is None:
            return m.group(0)
        changed = True
        return str(val)

    return _ARITH_REF_RE.sub(repl, text), changed


# ===========================================================================
# 2c. Fold  printf '%x' / '%03o'  on a constant
# ===========================================================================

_PRINTF_FMT_HEX = re.compile(
    r"""\$\(\s*printf\s+'(?P<fmt>%0?\d*[xXoO])'\s+
        (?P<num>\d+)\s*\)""",
    re.VERBOSE,
)
_PRINTF_FMT_HEX_BT = re.compile(
    r"""`\s*printf\s+'(?P<fmt>%0?\d*[xXoO])'\s+
        (?P<num>\d+)\s*`""",
    re.VERBOSE,
)


def _apply_printf_int(fmt: str, n: int) -> str:
    m = re.match(r"%(?P<zero>0?)(?P<width>\d*)(?P<conv>[xXoO])", fmt)
    assert m
    width = int(m.group("width") or 0)
    zero = m.group("zero") == "0"
    conv = m.group("conv").lower()
    s = format(n, conv)
    if width and len(s) < width:
        s = ("0" if zero else " ") * (width - len(s)) + s
    return s


def fold_printf_int(text: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        try:
            n = int(m.group("num"), 10)
        except ValueError:
            return m.group(0)
        changed = True
        return _apply_printf_int(m.group("fmt"), n)

    text = _PRINTF_FMT_HEX.sub(repl, text)
    text = _PRINTF_FMT_HEX_BT.sub(repl, text)
    return text, changed


# ===========================================================================
# 2d. Unroll byte-emitting loops
# ===========================================================================

_FOR_LIST_RE = re.compile(
    r"""\bfor\s+(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s+in\s+
        (?P<items>(?:-?\d+\s+)*)(?P<last>-?\d+)\s*;
        \s*do\s+(?P<body>.*?)\s*;\s*done""",
    re.VERBOSE | re.DOTALL,
)

_BODY_PRINTF_RE = re.compile(
    r"""^\s*
        printf\s+
        (?P<outer>['"])
        (?P<prefix>\\)
        (?:
            \$\s*\(\s*printf\s+'(?P<ofmt>%0?\d*[ox])'\s+
            \$\(\(\s*(?P<oexpr>[^()]*?)\s*\)\)\s*\)
          | (?P<literal_esc>0?[0-7]{1,3}|x[0-9A-Fa-f]{1,2})
        )
        (?P=outer)\s*$
    """,
    re.VERBOSE,
)


def _render_byte_as_bash(ch: str) -> str:
    o = ord(ch)
    if 32 <= o < 127 and ch not in ("'", "\\"):
        return ch
    return "\\x%02x" % o


def try_unroll_byte_loops(text: str, table: dict[str, str]) -> tuple[str, bool]:
    changed = False

    def repl_loop(m: re.Match) -> str:
        nonlocal changed
        var = m.group("var")
        items_str = (m.group("items") or "") + (m.group("last") or "")
        items = [int(x) for x in items_str.split()] if items_str else []
        if not items or len(items) > MAX_LOOP_BYTES:
            return m.group(0)

        bm = _BODY_PRINTF_RE.match(m.group("body").strip())
        if not bm:
            return m.group(0)

        out_chars: list[str] = []
        for it in items:
            if bm.group("oexpr") is None:
                lit = bm.group("literal_esc")
                if lit.startswith("x"):
                    out_chars.append(chr(int(lit[1:], 16)))
                else:
                    out_chars.append(chr(int(lit, 8)))
                continue

            local = dict(table)
            local[var] = str(it)
            val = eval_arith(bm.group("oexpr"), local)
            if val is None:
                return m.group(0)

            fmt = bm.group("ofmt")
            if fmt.endswith("o"):
                r = format(val, "o")
                if len(r) > 3:
                    return m.group(0)
                out_chars.append(chr(int(r.zfill(3), 8)))
            else:
                r = format(val, "x")
                if len(r) > 2:
                    return m.group(0)
                out_chars.append(chr(int(r, 16)))

        body_out = "".join(_render_byte_as_bash(c) for c in out_chars)
        body_out = body_out.replace("'", "'\\''")
        changed = True
        return "'" + body_out + "'"

    return _FOR_LIST_RE.sub(repl_loop, text), changed


# ===========================================================================
# 2e. Inline XOR:  \x$((65 ^ 42))
# ===========================================================================

_XOR_INLINE_RE = re.compile(
    r"""\\x\$\(\(\s*(?P<expr>[^()]*?)\s*\)\)""",
    re.VERBOSE,
)


def try_decode_xor_inline(text: str, table: dict[str, str]) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        val = eval_arith(m.group("expr"), table)
        if val is None or not (0 <= val <= 0xFFFFFFFF):
            return m.group(0)
        if val <= 0xFF:
            changed = True
            return "\\x%02x" % val
        bs = val.to_bytes(4, "big").lstrip(b"\x00")
        changed = True
        return "".join("\\x%02x" % b for b in bs)

    return _XOR_INLINE_RE.sub(repl, text), changed


# ===========================================================================
# 3. Variable expansion
# ===========================================================================

_VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def expand_vars(expr: str, table: dict[str, str], depth: int = 0) -> str:
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
    m = _EVAL_RE.search(text)
    if not m:
        return None
    if m.group("dq") is not None:
        return unescape_dq(m.group("dq"))
    if m.group("sq") is not None:
        return m.group("sq")
    return m.group("bare")


# ===========================================================================
# 5a. printf '%b' '...'
# ===========================================================================

_PRINTF_RE = re.compile(
    r"""\bprintf\s+
        (?P<fmt>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
        (?P<args>(?:\s+(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"))*)
    """,
    re.VERBOSE,
)

_STR_LIT_RE = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"")


def _decode_printf(fmt: str, args: list[str]) -> str | None:
    out: list[str] = []
    fi = ai = 0
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
            out.append(unescape_ansi_c(a) if conv == "b" else a)
            continue
        return None
    return "".join(out)


def try_decode_printf(text: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        raw = m.group("fmt")
        if raw.startswith("'"):
            fmt = raw[1:-1]
        else:
            fmt = unescape_dq(raw[1:-1])
        fmt = unescape_ansi_c(fmt)

        args: list[str] = []
        for sm in _STR_LIT_RE.finditer(m.group("args") or ""):
            if sm.group(1) is not None:
                args.append(sm.group(1))
            else:
                args.append(unescape_dq(sm.group(2)))
        if any("$" in a for a in args):
            return m.group(0)
        decoded = _decode_printf(fmt, args)
        if decoded is None:
            return m.group(0)
        changed = True
        return decoded

    return _PRINTF_RE.sub(repl, text), changed


# ===========================================================================
# 5b. echo -e '...'
# ===========================================================================

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
        body = raw[1:-1]
        if raw.startswith('"'):
            body = unescape_dq(body)
        changed = True
        return unescape_ansi_c(body)

    return _ECHO_E_RE.sub(repl, text), changed


# ===========================================================================
# 5c. base64 -d  (here-string and heredoc forms; the pipe form is handled
#                 by the pipeline evaluator below)
# ===========================================================================

_B64_HERESTR_RE = re.compile(
    r"""base64\s+(?:-[dD]|--decode)\s*<<<\s*
        (?P<q>['"])(?P<data>[A-Za-z0-9+/=\s]*?)(?P=q)""",
    re.VERBOSE | re.DOTALL,
)
_B64_HEREDOC_RE = re.compile(
    r"""base64\s+(?:-[dD]|--decode)\s*<<\s*(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\s*\n
        (?P<data>.*?)\n(?P=tag)\b""",
    re.VERBOSE | re.DOTALL,
)


def _b64_try(s: str) -> str | None:
    try:
        cleaned = re.sub(r"\s+", "", s)
        cleaned += "=" * (-len(cleaned) % 4)
        raw = base64.b64decode(cleaned, validate=True)
        return _bytes_to_str(raw)
    except (binascii.Error, ValueError):
        return None


def try_decode_base64(text: str) -> tuple[str, bool]:
    changed = False

    def repl(m: re.Match) -> str:
        nonlocal changed
        dec = _b64_try(m.group("data"))
        if dec is None:
            return m.group(0)
        changed = True
        return emit_literal(dec)

    text = _B64_HERESTR_RE.sub(repl, text)
    text = _B64_HEREDOC_RE.sub(repl, text)
    return text, changed


# ===========================================================================
# 5f. gzip / xxd helpers
# ===========================================================================


def _gzip_try(data: str) -> str | None:
    """Attempt gzip decompression. Auto-detects gzip and zlib headers."""
    raw = _str_to_bytes(data)
    if raw is None:
        return None
    try:
        out = zlib.decompress(raw, wbits=zlib.MAX_WBITS | 32)
    except zlib.error:
        return None
    return _bytes_to_str(out)


def _xxd_try(data: str) -> str | None:
    """Reverse a plain hex dump (xxd -r -p)."""
    cleaned = re.sub(r"\s+", "", data)
    if not cleaned or len(cleaned) % 2 != 0:
        return None
    try:
        raw = bytes.fromhex(cleaned)
    except ValueError:
        return None
    return _bytes_to_str(raw)


def _rev_try(data: str) -> str:
    """rev(1): reverse each line of stdin."""
    return "\n".join(line[::-1] for line in data.split("\n"))


# ===========================================================================
# 5g. Pipeline evaluator
# ===========================================================================
# A "pipeline" here is:  STARTPREFIX <literal>  ( '|' STAGE )+
# where STARTPREFIX is `echo [-neE]*` or `printf [-neE]*` (or nothing, if
# the literal is already a bare quoted string, which happens after printf
# folding on an earlier pass), and each STAGE is one of the known decoders.

_PIPE_START_RE = re.compile(
    r"""(?:
            \b(?:echo|printf)\s+(?:-[neE]+\s+)?
            (?:
                \$'(?P<ansi1>(?:\\.|[^'\\])*)'
              | '(?P<sq1>[^']*)'
              | "(?P<dq1>(?:\\.|[^"\\])*)"
            )
          |
            (?:
                \$'(?P<ansi2>(?:\\.|[^'\\])*)'
              | '(?P<sq2>[^']*)'
              | "(?P<dq2>(?:\\.|[^"\\])*)"
            )
        )
    """,
    re.VERBOSE,
)


def _get_start_literal(m: re.Match) -> str | None:
    """Extract and decode the starting literal from a _PIPE_START_RE match."""
    for suffix in ("1", "2"):
        for kind in ("ansi", "sq", "dq"):
            val = m.group(kind + suffix)
            if val is None:
                continue
            if kind == "ansi":
                return unescape_ansi_c(val)
            if kind == "dq":
                return unescape_dq(val)
            return val
    return None


# One pipe stage:  | base64 -d   | zcat   | gunzip -c   | xxd -r -p
#                  | rev          | tr 'X' 'Y'
_PIPE_STAGE_RE = re.compile(
    r"""\s*\|\s*
        (?:
            base64\s+(?:-[dD]|--decode)\b
          | zcat\b
          | gunzip\b(?:\s+-c)?
          | xxd\s+-r(?:\s+-p)?
          | rev\b
          | tr\s+(?P<t1>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
               \s+
               (?P<t2>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
        )
    """,
    re.VERBOSE,
)


def _tr_expand_class(spec: str) -> list[str]:
    """Expand a tr SET like 'a-z' or 'A-Z0-9' into a list of chars."""
    chars: list[str] = []
    i = 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-":
            lo, hi = spec[i], spec[i + 2]
            if ord(lo) <= ord(hi):
                chars.extend(chr(x) for x in range(ord(lo), ord(hi) + 1))
                i += 3
                continue
        chars.append(spec[i])
        i += 1
    return chars


def _pipe_stage_apply(data: str, m: re.Match) -> str | None:
    """Apply one pipe stage to `data`. Return new data or None on failure."""
    stage = m.group(0).lower()
    if re.search(r"\bbase64\b", stage):
        return _b64_try(data)
    if re.search(r"\bzcat\b", stage) or re.search(r"\bgunzip\b", stage):
        return _gzip_try(data)
    if re.search(r"\bxxd\b", stage):
        return _xxd_try(data)
    if re.search(r"\brev\b", stage):
        return _rev_try(data)
    if re.search(r"\btr\b", stage):
        s1raw = m.group("t1")
        s2raw = m.group("t2")
        if s1raw is None or s2raw is None:
            return None
        set1 = _tr_expand_class(s1raw[1:-1])
        set2 = _tr_expand_class(s2raw[1:-1])
        if not set1 or not set2:
            return None
        if len(set2) < len(set1):
            set2 = set2 + [set2[-1]] * (len(set1) - len(set2))
        mapping = dict(zip(set1, set2))
        return "".join(mapping.get(ch, ch) for ch in data)
    return None


def try_decode_pipeline(text: str) -> tuple[str, bool]:
    """
    Walk the text, find every literal-to-pipe chain, and evaluate the chain
    stage by stage. Emits the decoded literal in place of the whole chain.
    Stops at the first stage that can't be applied, leaving the trailing
    `| stage…` visible for the analyst.
    """
    changed = False
    out: list[str] = []
    pos = 0

    while True:
        m = _PIPE_START_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break

        # Emit everything before this match.
        out.append(text[pos : m.start()])

        data = _get_start_literal(m)
        if data is None:
            out.append(text[m.start() : m.end()])
            pos = m.end()
            continue

        # Try to consume a chain of `| stage` after the literal.
        cur = m.end()
        stages = 0
        while True:
            sm = _PIPE_STAGE_RE.match(text, cur)
            if not sm:
                break
            new_data = _pipe_stage_apply(data, sm)
            if new_data is None:
                break
            data = new_data
            cur = sm.end()
            stages += 1

        if stages == 0:
            # Nothing we recognise followed this literal: emit it as-is.
            out.append(text[m.start() : m.end()])
            pos = m.end()
            continue

        out.append(emit_literal(data))
        changed = True
        pos = cur

    return "".join(out), changed


# ===========================================================================
# 5h. Single-command here-string decoders for xxd / zcat
# ===========================================================================

_XXD_HERESTR_RE = re.compile(
    r"""xxd\s+-r\s+-p\s*<<<\s*
        (?:
            \$'(?P<ansi>(?:\\.|[^'\\])*)'
          | '(?P<sq>[^']*)'
          | "(?P<dq>(?:\\.|[^"\\])*)"
        )
    """,
    re.VERBOSE | re.DOTALL,
)

_ZCAT_HERESTR_RE = re.compile(
    r"""(?:zcat|gunzip\s+-c)\s*<<<\s*
        (?:
            \$'(?P<ansi>(?:\\.|[^'\\])*)'
          | '(?P<sq>[^']*)'
          | "(?P<dq>(?:\\.|[^"\\])*)"
        )
    """,
    re.VERBOSE | re.DOTALL,
)


def _extract_here_str(m: re.Match) -> str | None:
    if m.group("ansi") is not None:
        return unescape_ansi_c(m.group("ansi"))
    if m.group("sq") is not None:
        return m.group("sq")
    if m.group("dq") is not None:
        return unescape_dq(m.group("dq"))
    return None


def try_decode_here_strings(text: str) -> tuple[str, bool]:
    changed = False

    def repl_xxd(m: re.Match) -> str:
        nonlocal changed
        raw = _extract_here_str(m)
        if raw is None:
            return m.group(0)
        dec = _xxd_try(raw)
        if dec is None:
            return m.group(0)
        changed = True
        return emit_literal(dec)

    def repl_zcat(m: re.Match) -> str:
        nonlocal changed
        raw = _extract_here_str(m)
        if raw is None:
            return m.group(0)
        dec = _gzip_try(raw)
        if dec is None:
            return m.group(0)
        changed = True
        return emit_literal(dec)

    text = _XXD_HERESTR_RE.sub(repl_xxd, text)
    text = _ZCAT_HERESTR_RE.sub(repl_zcat, text)
    return text, changed


# ===========================================================================
# 6. One deobfuscation pass
# ===========================================================================
# Order:
#   1. refresh assignment table
#   2. fold $((...)) arithmetic
#   3. fold printf '%x' / '%o' on constants
#   4. unroll byte-emitting for-loops
#   5. splice inline \x$((...)) XOR escapes
#   6. run pipeline evaluator (base64|zcat|xxd|rev|tr chains)
#   7. run single-command decoders (printf, echo -e, base64<<<, xxd<<<, zcat<<<)
#   8. splice the top-level eval


def deobfuscate_once(text: str) -> tuple[str, bool]:
    progress = False

    table = extract_assignments(text)

    text, ch = fold_arith(text, table)
    progress |= ch
    table = extract_assignments(text)

    text, ch = fold_printf_int(text)
    progress |= ch
    text, ch = try_unroll_byte_loops(text, table)
    progress |= ch
    text, ch = try_decode_xor_inline(text, table)
    progress |= ch

    for fn in (
        try_decode_pipeline,
        try_decode_printf,
        try_decode_echo_e,
        try_decode_base64,
        try_decode_here_strings,
    ):
        text, ch = fn(text)
        progress |= ch

    table = extract_assignments(text)
    payload = find_eval_payload(text)
    if payload is not None and table:
        expanded = expand_vars(payload, table)
        if expanded != payload:

            def repl(_m: re.Match) -> str:
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
    for _ in range(MAX_PASSES):
        text, progress = deobfuscate_once(text)
        if not progress:
            break
    return text


# ===========================================================================
# 9. Opaque-region report
# ===========================================================================
# After deobfuscation, scan for remnants that *look* like the output of an
# obfuscator we couldn't fully unwind. Useful for humans reading the result
# and for CI-style checks ("this script still contains 3 undecoded stages").

_ARITH_LEFTOVER_RE = re.compile(r"\$\(\(\s*([^()]*?)\s*\)\)")
_CMD_SUBST_RE = re.compile(r"\$\(")
_EVAL_LEFTOVER_RE = re.compile(r"\beval\b")
_B64_LEFTOVER_RE = re.compile(r"\bbase64\s+(?:-[dD]|--decode)\b")
_STAGE_LEFTOVER_RE = re.compile(r"\b(?:zcat|gunzip|xxd|rev|tr)\b")
_ESC_SEQ_RE = re.compile(r"\\x[0-9A-Fa-f]{2}")


def report_opaque(text: str) -> list[str]:
    """
    Return a list of human-readable notes about *remaining* obfuscation.
    Intentionally conservative: we only flag patterns that are almost
    always signs of undecoded layers, not ordinary shell code.
    """
    notes: list[str] = []
    for i, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for m in _ARITH_LEFTOVER_RE.finditer(line):
            notes.append(f"L{i}: unresolved arithmetic: $(({m.group(1)}))")

        if _EVAL_LEFTOVER_RE.search(line):
            notes.append(f"L{i}: eval remains: {stripped[:100]}")

        if _B64_LEFTOVER_RE.search(line):
            notes.append(f"L{i}: base64 -d remains: {stripped[:100]}")

        for kw in ("zcat", "gunzip", "xxd"):
            if re.search(r"\b" + kw + r"\b", line):
                notes.append(f"L{i}: {kw} remains: {stripped[:100]}")

        if len(_CMD_SUBST_RE.findall(line)) >= 3:
            n = len(_CMD_SUBST_RE.findall(line))
            notes.append(f"L{i}: heavy command substitution ({n} nested)")

        if len(stripped) > 200 and len(_ESC_SEQ_RE.findall(line)) > 5:
            notes.append(
                f"L{i}: long escaped line ({len(stripped)} chars, "
                f"{len(_ESC_SEQ_RE.findall(line))} \\x escapes)"
            )

    return notes


# ===========================================================================
# 8. CLI
# ===========================================================================


def default_output_path(inp: Path) -> Path:
    return inp.with_name(inp.name + OUTPUT_SUFFIX)


def process_file(inp: Path, out: Path | None, to_stdout: bool, report: bool) -> int:
    try:
        src = inp.read_text(errors="replace")
    except OSError as e:
        print(f"error: cannot read {inp}: {e}", file=sys.stderr)
        return 1

    try:
        result = deobfuscate(src)
    except Exception as e:
        print(f"error: deobfuscation failed for {inp}: {e}", file=sys.stderr)
        return 1

    if to_stdout:
        sys.stdout.write(result)
        if report:
            notes = report_opaque(result)
            if notes:
                sys.stderr.write("\n".join(notes) + "\n")
        return 0

    dest = out or default_output_path(inp)
    try:
        dest.write_text(result)
    except OSError as e:
        print(f"error: cannot write {dest}: {e}", file=sys.stderr)
        return 1

    print(f"  {inp}  ->  {dest}")

    if report:
        notes = report_opaque(result)
        rep = Path(str(dest) + REPORT_SUFFIX)
        try:
            rep.write_text("\n".join(notes) + ("\n" if notes else ""))
            print(f"        report: {rep}  ({len(notes)} note(s))")
        except OSError as e:
            print(f"warning: cannot write report {rep}: {e}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Static deobfuscator for common bash obfuscation styles."
    )
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument(
        "--report",
        action="store_true",
        help="write <out>.report.txt with remaining obfuscation notes",
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
        rc |= process_file(f, args.output, args.stdout, args.report)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
