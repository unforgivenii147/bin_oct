#!/data/data/com.termux/files/home/.local/bin/python
# -*- coding: utf-8 -*-
"""
webclean.py — Unified comment stripper for web files (HTML, CSS, JS, TS).

Merges the behavior of the following original scripts:

    clean_css.py    ->  webclean.py css
    cleancss2.py    ->  webclean.py css --no-preserve-newlines --collapse-blank-lines --remove-whole-line-comments
    cleanjs.py      ->  webclean.py js
    cleants.py      ->  webclean.py ts
    clean_html.py   ->  webclean.py all
    cleanhtml.py    ->  webclean.py all
    cleanhtmlre.py  ->  webclean.py inline <file.html> [--output-suffix _cleaned]
    rmcss.py        ->  webclean.py regex --extensions .html .htm .css
    rmhtml.py       ->  webclean.py html --approach regex --unescape-entities --extensions .html .htm .xml
    rmjsts.py       ->  webclean.py js  --approach regex   (and  ts --approach regex)

Third-party dependencies (install exactly as the originals required):

    pip install tree-sitter tree-sitter-html tree-sitter-css \\
                tree-sitter-javascript tree-sitter-typescript

Only the `tree-sitter` code paths require those packages; the `regex`,
`inline`, and `--approach regex` code paths are pure standard library.
"""

from __future__ import annotations

import argparse
import contextlib
import multiprocessing as mp
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# ============================================================================
#  Constants
# ============================================================================

DEFAULT_WORKERS: int = 8

EXT_TO_LANG: dict[str, str] = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".jsx": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".mts": "ts",
    ".cts": "ts",
}

LANG_TO_EXTS: dict[str, set[str]] = {}
for _ext, _lang in EXT_TO_LANG.items():
    LANG_TO_EXTS.setdefault(_lang, set()).add(_ext)

# Default newline-preservation policy per language (matches originals).
DEFAULT_PRESERVE_NEWLINES: dict[str, bool] = {
    "css": True,
    "js": True,
    "ts": True,
    "html": False,
}

# ============================================================================
#  Tree-sitter parser factory (lazy, per-process cache)
# ============================================================================

_PARSER_CACHE: dict[str, object] = {}


def get_parser(lang: str, tsx: bool = False):
    """Return a cached tree-sitter Parser for `lang`.

    `lang` may be 'html', 'css', 'js', 'ts' (or 'tsx' shorthand for ts+tsx grammar).
    """
    if lang == "tsx":
        lang, tsx = "ts", True
    key = f"{lang}:{int(tsx)}"
    if key in _PARSER_CACHE:
        return _PARSER_CACHE[key]

    from tree_sitter import Language, Parser  # lazy third-party import

    if lang == "html":
        import tree_sitter_html as m

        lang_obj = Language(m.language())
    elif lang == "css":
        import tree_sitter_css as m

        lang_obj = Language(m.language())
    elif lang == "js":
        import tree_sitter_javascript as m

        lang_obj = Language(m.language())
    elif lang == "ts":
        import tree_sitter_typescript as m

        fn = m.language_tsx if tsx else m.language_typescript
        lang_obj = Language(fn())
    else:
        raise ValueError(f"unknown language: {lang}")

    try:
        parser = Parser(lang_obj)
    except TypeError:
        parser = Parser()
        try:
            parser.language = lang_obj
        except AttributeError:
            parser.set_language(lang_obj)

    _PARSER_CACHE[key] = parser
    return parser


def ts_comment_ranges(text: bytes, parser) -> list[tuple[int, int]]:
    """Collect (start_byte, end_byte) for every comment node in `text`."""
    tree = parser.parse(text)
    ranges: list[tuple[int, int]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
            continue
        stack.extend(node.children)
    ranges.sort()
    return ranges


# ---------------------------------------------------------------------------
#  HTML embedded <script>/<style> handling
# ---------------------------------------------------------------------------

_NO_STRIP_SCRIPT_TYPES = (
    b"application/json",
    b"application/ld+json",
    b"importmap",
    b"speculationrules",
    b"text/template",
    b"text/x-template",
    b"text/plain",
    b"application/xml",
)
_NO_STRIP_STYLE_TYPES = (
    b"text/less",
    b"text/scss",
    b"text/sass",
    b"text/stylus",
    b"text/x-scss",
    b"text/x-sass",
)


def detect_script_lang(tag_bytes: bytes) -> Optional[str]:
    """Return 'js' | 'ts' | 'tsx' | None for a <script ...> start tag."""
    low = tag_bytes.lower()
    if b"type=" not in low and b"language=" not in low:
        return "js"
    if any(
        t in low for t in (b"text/typescript", b"application/typescript", b"typescript")
    ):
        return "ts"
    if any(t in low for t in (b"text/tsx", b"application/tsx")):
        return "tsx"
    if any(t in low for t in _NO_STRIP_SCRIPT_TYPES):
        return None
    if any(
        t in low
        for t in (
            b"javascript",
            b"ecmascript",
            b"module",
            b"text/jsx",
            b"application/jsx",
        )
    ):
        return "js"
    return None


def detect_style_lang(tag_bytes: bytes) -> Optional[str]:
    """Return 'css' | None for a <style ...> start tag."""
    low = tag_bytes.lower()
    if any(t in low for t in _NO_STRIP_STYLE_TYPES):
        return None
    return "css"


def find_embedded_blocks(text: bytes, html_parser) -> list[tuple[int, int, str]]:
    """Return (start, end, lang) for each <script>/<style> raw_text body."""
    tree = html_parser.parse(text)
    out: list[tuple[int, int, str]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "element":
            start_tag = raw_text = None
            for child in node.children:
                if child.type == "start_tag":
                    start_tag = child
                elif child.type == "raw_text":
                    raw_text = child
            if (
                start_tag is not None
                and raw_text is not None
                and raw_text.end_byte > raw_text.start_byte
            ):
                tag = text[start_tag.start_byte : start_tag.end_byte].lower()
                if tag.startswith(b"<script"):
                    lang = detect_script_lang(tag)
                elif tag.startswith(b"<style"):
                    lang = detect_style_lang(tag)
                else:
                    lang = None
                if lang is not None:
                    out.append((raw_text.start_byte, raw_text.end_byte, lang))
        stack.extend(node.children)
    return out


# ============================================================================
#  Regex / state-machine comment scanners
# ============================================================================

_RE_CSS_COMMENT = re.compile(rb"/\*.*?\*/", re.DOTALL)
_RE_HTML_ALL = re.compile(rb"<!--.*?-->", re.DOTALL)
_RE_HTML_SAFE = re.compile(rb"<!--(?!\[if).*?-->", re.DOTALL)

_QUOTES = (ord('"'), ord("'"), ord("`"))
_BACKSLASH = ord("\\")
_SLASH = ord("/")
_STAR = ord("*")
_NL = ord("\n")
_CR = ord("\r")


def regex_css_ranges(text: bytes) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _RE_CSS_COMMENT.finditer(text)]


def regex_html_ranges(text: bytes, keep_conditional: bool) -> list[tuple[int, int]]:
    rx = _RE_HTML_SAFE if keep_conditional else _RE_HTML_ALL
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def regex_js_ranges(text: bytes) -> list[tuple[int, int]]:
    """Lightweight scanner: skips strings/templates, records // and /* */."""
    ranges: list[tuple[int, int]] = []
    i, n = 0, len(text)
    quote = -1
    while i < n:
        c = text[i]
        if quote != -1:
            if c == _BACKSLASH and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = -1
            i += 1
            continue
        if c in _QUOTES:
            quote = c
            i += 1
            continue
        if c == _SLASH and i + 1 < n:
            nxt = text[i + 1]
            if nxt == _SLASH:
                start = i
                i += 2
                while i < n and text[i] not in (_NL, _CR):
                    i += 1
                ranges.append((start, i))
                continue
            if nxt == _STAR:
                start = i
                i += 2
                while i + 1 < n and not (text[i] == _STAR and text[i + 1] == _SLASH):
                    i += 1
                i = min(i + 2, n)
                ranges.append((start, i))
                continue
        i += 1
    return ranges


# ============================================================================
#  Range removal + post-processing
# ============================================================================


def remove_ranges(
    text: bytes, ranges: list[tuple[int, int]], preserve_newlines: bool
) -> bytes:
    """Delete each range; if `preserve_newlines`, keep \\n/\\r inside them."""
    if not ranges:
        return text
    ranges = sorted(ranges)
    out = bytearray()
    prev = 0
    for start, end in ranges:
        out.extend(text[prev:start])
        if preserve_newlines:
            for b in text[start:end]:
                if b in (_NL, _CR):
                    out.append(b)
        prev = end
    out.extend(text[prev:])
    return bytes(out)


def css_remove_whole_line_comments(
    text: bytes, ranges: list[tuple[int, int]]
) -> tuple[bytes, int]:
    """Delete each comment; if it is alone on a line, delete the whole line.

    Port of cleancss2.py's per-comment strategy.
    """
    if not ranges:
        return text, 0
    ranges = sorted(ranges)
    parts: list[bytes] = []
    prev = 0
    count = 0
    for start, end in ranges:
        before = text[prev:start]
        line_start = text.rfind(b"\n", 0, start) + 1
        prefix = text[line_start:start]
        if prefix.strip() == b"":
            nl = text.find(b"\n", end)
            nl = len(text) if nl == -1 else nl + 1
            if text[end:nl].strip() == b"":
                parts.append(before[: len(prefix)])
                prev = nl
                count += 1
                continue
        parts.append(before)
        prev = end
        count += 1
    parts.append(text[prev:])
    return b"".join(parts), count


def css_collapse_blank_lines(text: bytes) -> bytes:
    while b"\n\n\n" in text:
        text = text.replace(b"\n\n\n", b"\n\n")
    return (text.strip(b"\n") + b"\n") if text else b""


def unescape_html_entities(text: bytes) -> bytes:
    return text.replace(b"&lt;", b"<").replace(b"&gt;", b">").replace(b"&amp;", b"&")


def apply_removal(
    text: bytes, lang: str, ranges: list[tuple[int, int]], preserve: bool, opts: "Job"
) -> tuple[bytes, int]:
    """Generic post-processing after comment ranges have been identified."""
    if not ranges:
        return text, 0
    if lang == "css" and opts.remove_whole_line_comments:
        new_text, n = css_remove_whole_line_comments(text, ranges)
    else:
        new_text = remove_ranges(text, ranges, preserve)
        n = len(ranges)
    if lang == "css" and opts.collapse_blank_lines:
        new_text = css_collapse_blank_lines(new_text)
    if lang == "html" and opts.unescape_entities:
        new_text = unescape_html_entities(new_text)
    return new_text, n


# ============================================================================
#  Job / Result dataclasses
# ============================================================================


@dataclass(frozen=True)
class Job:
    path: str
    lang: str  # 'css' | 'js' | 'ts' | 'html'
    approach: str  # 'tree-sitter' | 'regex'
    preserve_newlines: Optional[bool]  # None -> per-language default
    collapse_blank_lines: bool
    remove_whole_line_comments: bool
    embedded: bool
    unescape_entities: bool
    keep_conditional: bool
    dry_run: bool


@dataclass
class Result:
    path: str
    changed: bool
    comments_removed: int
    error: Optional[str] = None


# ============================================================================
#  Core strip dispatch
# ============================================================================


def strip_text(text: bytes, lang: str, approach: str, opts: Job) -> tuple[bytes, int]:
    """Return (new_text, comments_removed) for one file's bytes."""
    preserve = opts.preserve_newlines
    if preserve is None:
        preserve = DEFAULT_PRESERVE_NEWLINES.get(lang, True)

    if approach == "tree-sitter":
        if lang == "html":
            return _strip_html_ts(text, opts, preserve)
        tsx = opts.path.lower().endswith(".tsx")
        parser = get_parser(lang, tsx=tsx)
        ranges = ts_comment_ranges(text, parser)
        return apply_removal(text, lang, ranges, preserve, opts)

    # regex / state-machine approach
    if lang == "css":
        ranges = regex_css_ranges(text)
    elif lang == "html":
        ranges = regex_html_ranges(text, opts.keep_conditional)
    else:
        ranges = regex_js_ranges(text)
    return apply_removal(text, lang, ranges, preserve, opts)


def _strip_html_ts(text: bytes, opts: Job, preserve: bool) -> tuple[bytes, int]:
    """HTML via tree-sitter; optionally also strips embedded JS/CSS."""
    html_parser = get_parser("html")

    if not opts.embedded:
        ranges = ts_comment_ranges(text, html_parser)
        return apply_removal(text, "html", ranges, preserve, opts)

    # 1) inner embed stripping
    embeds = find_embedded_blocks(text, html_parser)
    replacements: list[tuple[int, int, bytes]] = []
    total = 0
    for s, e, inner_lang in embeds:
        inner = text[s:e]
        tsx = inner_lang == "tsx"
        parser = get_parser(inner_lang, tsx=tsx)
        inner_ranges = ts_comment_ranges(inner, parser)
        if not inner_ranges:
            continue
        new_inner = remove_ranges(inner, inner_ranges, preserve_newlines=True)
        if new_inner != inner:
            replacements.append((s, e, new_inner))
            total += len(inner_ranges)

    result = text
    for s, e, new in sorted(replacements, key=lambda x: x[0], reverse=True):
        result = result[:s] + new + result[e:]

    # 2) outer HTML comments (positions recomputed on the modified text)
    ranges = ts_comment_ranges(result, html_parser)
    result, n = apply_removal(result, "html", ranges, preserve, opts)
    return result, total + n


# ============================================================================
#  File I/O
# ============================================================================


def atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically, preserving mode bits and fsyncing."""
    st = path.stat()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, st.st_mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def process_job(job: Job) -> Result:
    """Top-level worker: read, strip, write (unless dry-run)."""
    path = Path(job.path)
    try:
        if not path.is_file():
            return Result(job.path, False, 0, "Not a regular file")
        text = path.read_bytes()
    except OSError as exc:
        return Result(job.path, False, 0, f"Filesystem error: {exc}")

    if not text:
        return Result(job.path, False, 0)

    try:
        new_text, n = strip_text(text, job.lang, job.approach, job)
    except Exception as exc:  # noqa: BLE001 - surface any parser error to caller
        return Result(job.path, False, 0, f"{type(exc).__name__}: {exc}")

    if n == 0 or new_text == text:
        return Result(job.path, False, 0)

    if not job.dry_run:
        try:
            atomic_write(path, new_text)
        except OSError as exc:
            return Result(job.path, False, n, f"Write error: {exc}")
    return Result(job.path, True, n)


# ============================================================================
#  File discovery
# ============================================================================


def discover_files(
    paths: list[str], extensions: set[str], follow_symlinks: bool
) -> list[Path]:
    """Return a de-duplicated, sorted list of candidate files."""
    seen: set[Path] = set()
    out: list[Path] = []
    for raw in paths:
        root = Path(raw)
        try:
            if root.is_file():
                if root.suffix.lower() in extensions:
                    rp = root.resolve()
                    if rp not in seen:
                        seen.add(rp)
                        out.append(root)
            elif root.is_dir():
                for child in root.rglob("*"):
                    try:
                        if not child.is_file():
                            continue
                        if not follow_symlinks and child.is_symlink():
                            continue
                        if child.suffix.lower() in extensions:
                            rp = child.resolve()
                            if rp not in seen:
                                seen.add(rp)
                                out.append(child)
                    except OSError:
                        continue
            else:
                print(f"warning: path not found: {root}", file=sys.stderr)
        except OSError as exc:
            print(f"warning: cannot scan {root}: {exc}", file=sys.stderr)
    out.sort(key=lambda p: str(p))
    return out


# ============================================================================
#  Multi-file orchestration
# ============================================================================


def run_jobs(jobs: list[Job], workers: int, dry_run: bool) -> int:
    """Execute jobs (serially or in a process pool), print a summary."""
    if not jobs:
        print("No files found to process.", file=sys.stderr)
        return 0

    workers = max(1, workers)
    changed = errors = total_removed = 0
    verb = "WOULD UPDATE" if dry_run else "UPDATED"

    def report(r: Result) -> None:
        nonlocal changed, errors, total_removed
        if r.error:
            errors += 1
            print(f"ERROR: {r.path}: {r.error}", file=sys.stderr)
        elif r.changed:
            changed += 1
            total_removed += r.comments_removed
            print(f"{verb}: {r.path} ({r.comments_removed} comment(s) removed)")

    if workers == 1:
        for job in jobs:
            report(process_job(job))
    else:
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=workers) as pool:
            futures = [pool.apply_async(process_job, (j,)) for j in jobs]
            for fut in futures:
                try:
                    report(fut.get())
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(
                        f"ERROR: worker failed: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

    print()
    print(f"Files scanned : {len(jobs)}")
    print(f"Files changed : {changed}")
    print(f"Comments out  : {total_removed}")
    if errors:
        print(f"Errors        : {errors}")
    return 1 if errors else 0


# ============================================================================
#  ---------------------------------------------------------------------------
#  inline subcommand  (cleanhtmlre.py port)
#  ---------------------------------------------------------------------------
# ============================================================================

_RE_LINK_STYLESHEET = re.compile(
    r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>', re.IGNORECASE
)
_RE_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_SCRIPT_SRC = re.compile(
    r'<script\b([^>]*)\bsrc=["\']([^"\']+)["\']([^>]*)>\s*</script>', re.IGNORECASE
)
_RE_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_RE_SCRIPT_INLINE = re.compile(
    r"<script\b(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
_RE_HTML_COMMENT_SAFE_STR = re.compile(r"<!--(?!\[if).*?-->", re.DOTALL)
_RE_CSS_COMMENT_STR = re.compile(r"/\*.*?\*/", re.DOTALL)


def _load_asset(src: str, base: Path) -> Optional[str]:
    """Fetch an external CSS/JS asset (http(s)://, //, or relative path)."""
    try:
        if src.startswith(("http://", "https://")):
            with urllib.request.urlopen(src, timeout=10) as r:
                enc = r.headers.get_content_charset() or "utf-8"
                return r.read().decode(enc, errors="replace")
        if src.startswith("//"):
            with urllib.request.urlopen("https:" + src, timeout=10) as r:
                enc = r.headers.get_content_charset() or "utf-8"
                return r.read().decode(enc, errors="replace")
        if src.startswith("data:"):
            return None
        p = (base / src.lstrip("/")).resolve()
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not load asset '{src}': {exc}", file=sys.stderr)
    return None


def _js_strip_str(js: str) -> str:
    """Strip // and /* */ comments from a JS/TS string."""
    out: list[str] = []
    i, n = 0, len(js)
    quote: Optional[str] = None
    while i < n:
        c = js[i]
        if quote is not None:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(js[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ('"', "'", "`"):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            while i < n and js[i] != "\n":
                i += 1
            if i < n:
                out.append("\n")
                i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":
            i += 2
            while i + 1 < n and js[i : i + 2] != "*/":
                if js[i] == "\n":
                    out.append("\n")
                i += 1
            i = min(i + 2, n)
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _inline_html(src: str, base_dir: Path, keep_conditional: bool) -> str:
    # 1) <link rel=stylesheet> -> <style>
    def repl_link(m: re.Match) -> str:
        tag = m.group(0)
        hm = _RE_HREF.search(tag)
        if not hm:
            return tag
        css = _load_asset(hm.group(1), base_dir)
        if css is None:
            return tag
        return f"<style>{_RE_CSS_COMMENT_STR.sub('', css)}</style>"

    src = _RE_LINK_STYLESHEET.sub(repl_link, src)

    # 2) <script src=...></script> -> <script>...</script>
    def repl_script_src(m: re.Match) -> str:
        pre, src_url, post = m.groups()
        js = _load_asset(src_url, base_dir)
        if js is None:
            return m.group(0)
        js = _js_strip_str(js)
        attrs = re.sub(r'\ssrc=["\'][^"\']+["\']', "", pre + post, flags=re.IGNORECASE)
        return f"<script{attrs}>{js}</script>"

    src = _RE_SCRIPT_SRC.sub(repl_script_src, src)

    # 3) inline <style>...</style> bodies
    def repl_style(m: re.Match) -> str:
        head = m.group(0).split(">", 1)[0] + ">"
        return f"{head}{_RE_CSS_COMMENT_STR.sub('', m.group(1))}</style>"

    src = _RE_STYLE_BLOCK.sub(repl_style, src)

    # 4) inline <script>...</script> bodies
    def repl_script_inline(m: re.Match) -> str:
        attrs, body = m.groups()
        return f"<script{attrs}>{_js_strip_str(body)}</script>"

    src = _RE_SCRIPT_INLINE.sub(repl_script_inline, src)

    # 5) outer HTML comments
    rx = (
        _RE_HTML_COMMENT_SAFE_STR
        if keep_conditional
        else re.compile(r"<!--.*?-->", re.DOTALL)
    )
    src = rx.sub("", src)

    # 6) tidy blank lines
    return re.sub(r"\n\s*\n+", "\n\n", src)


def cmd_inline(args: argparse.Namespace) -> int:
    if not args.paths:
        print("error: inline requires an input HTML file", file=sys.stderr)
        return 2
    in_path = Path(args.paths[0]).expanduser().resolve()
    if not in_path.is_file():
        print(f"error: file not found: {in_path}", file=sys.stderr)
        return 1

    try:
        src = in_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {in_path}: {exc}", file=sys.stderr)
        return 1

    out_src = _inline_html(src, in_path.parent, keep_conditional=True)
    if args.in_place:
        out_path = in_path
    else:
        out_path = in_path.with_name(f"{in_path.stem}{args.output_suffix}.html")
    try:
        out_path.write_text(out_src, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {out_path}: {exc}", file=sys.stderr)
        return 1
    print(f"Cleaned file written to: {out_path}")
    return 0


# ============================================================================
#  CLI
# ============================================================================


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="Files or directories to process (default: cwd).",
    )
    p.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Worker processes (default: {DEFAULT_WORKERS}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symlinked files when walking directories.",
    )
    p.add_argument(
        "--preserve-newlines",
        dest="preserve_newlines",
        action="store_true",
        default=None,
        help="Keep \\n/\\r that occur inside removed comments.",
    )
    p.add_argument(
        "--no-preserve-newlines",
        dest="preserve_newlines",
        action="store_false",
        help="Delete the entire comment bytes (no newline preservation).",
    )
    p.add_argument(
        "--collapse-blank-lines",
        action="store_true",
        help="Collapse \\n\\n\\n+ to \\n\\n and trim trailing blanks (CSS).",
    )
    p.add_argument(
        "--remove-whole-line-comments",
        action="store_true",
        help="Delete whole line when a comment is alone on it (CSS).",
    )
    p.add_argument(
        "--embedded",
        dest="embedded",
        action="store_true",
        default=True,
        help="Also strip comments inside <script>/<style> (HTML).",
    )
    p.add_argument(
        "--no-embedded",
        dest="embedded",
        action="store_false",
        help="Do not descend into embedded <script>/<style> blocks.",
    )
    p.add_argument(
        "--unescape-entities",
        action="store_true",
        help="Also unescape &lt; &gt; &amp; (HTML regex mode).",
    )
    p.add_argument(
        "--keep-conditional",
        action="store_true",
        help="Preserve IE conditional comments <!--[if ...]> in regex HTML.",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webclean.py",
        description="Strip comments from HTML / CSS / JS / TS files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ---- language subcommands ------------------------------------------------
    for name, help_text in (
        ("css", "Strip CSS comments."),
        ("js", "Strip JavaScript comments."),
        ("ts", "Strip TypeScript comments."),
        ("html", "Strip HTML comments (optionally embedded)."),
        ("all", "Strip comments from every supported file type."),
    ):
        sp = sub.add_parser(name, help=help_text)
        _add_common_flags(sp)
        sp.add_argument(
            "--approach",
            choices=("tree-sitter", "regex"),
            default="tree-sitter",
            help="Engine to use (default: tree-sitter).",
        )
        sp.add_argument(
            "--extensions",
            nargs="+",
            default=None,
            help="Override the set of file extensions to scan.",
        )

    # ---- regex subcommand ----------------------------------------------------
    sp = sub.add_parser(
        "regex", help="Regex/state-machine stripping across extensions."
    )
    _add_common_flags(sp)
    sp.add_argument(
        "--extensions",
        nargs="+",
        default=sorted(EXT_TO_LANG.keys()),
        help="Extensions to process (default: all supported).",
    )

    # ---- inline subcommand ---------------------------------------------------
    sp = sub.add_parser(
        "inline",
        help="Inline external CSS/JS in an HTML file and strip "
        "comments (cleanhtmlre.py).",
    )
    sp.add_argument("paths", nargs="*")
    sp.add_argument(
        "--output-suffix",
        default="_cleaned",
        help="Suffix for the output file (default: _cleaned).",
    )
    sp.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file instead of writing a new file.",
    )

    return p


# ---- command handlers --------------------------------------------------------


def _make_job(path: Path, lang: str, args: argparse.Namespace) -> Job:
    def g(name: str, default):
        return getattr(args, name, default)

    return Job(
        path=str(path),
        lang=lang,
        approach=g("approach", "tree-sitter"),
        preserve_newlines=g("preserve_newlines", None),
        collapse_blank_lines=g("collapse_blank_lines", False),
        remove_whole_line_comments=g("remove_whole_line_comments", False),
        embedded=g("embedded", True),
        unescape_entities=g("unescape_entities", False),
        keep_conditional=g("keep_conditional", False),
        dry_run=g("dry_run", False),
    )


def cmd_language(args: argparse.Namespace, lang: str) -> int:
    if args.approach == "tree-sitter":
        try:
            import tree_sitter  # noqa: F401
        except ImportError as exc:
            print(
                f"error: tree-sitter not installed ({exc}). "
                f"Use --approach regex or install it.",
                file=sys.stderr,
            )
            return 2
    exts = set(args.extensions) if args.extensions else set(LANG_TO_EXTS[lang])
    files = discover_files(args.paths or ["."], exts, args.follow_symlinks)
    jobs = [_make_job(f, lang, args) for f in files]
    return run_jobs(jobs, args.workers, args.dry_run)


def cmd_all(args: argparse.Namespace) -> int:
    if args.approach == "tree-sitter":
        try:
            import tree_sitter  # noqa: F401
        except ImportError as exc:
            print(
                f"error: tree-sitter not installed ({exc}). Use --approach regex.",
                file=sys.stderr,
            )
            return 2
    exts = set(args.extensions) if args.extensions else set(EXT_TO_LANG.keys())
    files = discover_files(args.paths or ["."], exts, args.follow_symlinks)
    jobs = []
    for f in files:
        lang = EXT_TO_LANG.get(f.suffix.lower())
        if lang is None:
            continue
        jobs.append(_make_job(f, lang, args))
    return run_jobs(jobs, args.workers, args.dry_run)


def cmd_regex(args: argparse.Namespace) -> int:
    exts = {
        e.lower() if e.startswith(".") else "." + e.lower() for e in args.extensions
    }
    files = discover_files(args.paths or ["."], exts, args.follow_symlinks)
    jobs = []
    for f in files:
        lang = EXT_TO_LANG.get(f.suffix.lower())
        if lang is None:
            # Unknown extension -> fall back to regex HTML behavior
            lang = "html"
        args_approach = "regex"
        job = Job(
            path=str(f),
            lang=lang,
            approach=args_approach,
            preserve_newlines=args.preserve_newlines,
            collapse_blank_lines=args.collapse_blank_lines,
            remove_whole_line_comments=args.remove_whole_line_comments,
            embedded=False,
            unescape_entities=args.unescape_entities,
            keep_conditional=args.keep_conditional,
            dry_run=args.dry_run,
        )
        jobs.append(job)
    return run_jobs(jobs, args.workers, args.dry_run)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inline":
        return cmd_inline(args)
    if args.command == "all":
        return cmd_all(args)
    if args.command == "regex":
        return cmd_regex(args)
    return cmd_language(args, args.command)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
