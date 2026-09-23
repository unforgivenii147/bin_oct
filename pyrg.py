#!/data/data/com.termux/files/home/.local/bin/python
"""pyrg — ripgrep-like recursive search in Python.

A single-file, dependency-light re-implementation of the parts of ripgrep
that matter for interactive and scripted use.

Highlights over the previous iteration:
    * -t/--type presets (py, md, json, log, ...)
    * -A/-B/-C context lines, with '--' separators between groups
    * -v/--invert-match
    * --stats (files searched / matched / matches / elapsed)
    * --no-messages, otherwise unreadable files report to stderr
    * -M/--max-count N
    * -q/--quiet (exit code only)
    * --json (one JSON object per match)
    * .gitignore / .ignore awareness with --no-ignore opt-out
    * --files (list candidates, do not search)
    * -o/--only-matching and --replace REPL (with backrefs)
    * --multiline (regex over whole file, DOTALL)
    * --encoding ENC
    * -L/--follow symlinks with cycle detection
    * --sort path|none
    * --heading / --no-heading
    * --max-depth N, --exclude-dir NAME
    * --files-without-match
    * per-directory filename colors
    * ProcessPoolExecutor + as_completed (streaming results)
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import json
import os
import re
import sys
import time
from collections.abc import Generator, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from dh import is_binary
from fastwalk import walk_files  # noqa: F401  (kept for API compatibility)
from loguru import logger

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logger.remove()
logger.add("/data/data/com.termux/files/home/tmp/apps/pyrg.log")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

IGNORED_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}

# Curated extension sets for -t/--type (item 1).
TYPE_PRESETS: dict[str, set[str]] = {
    "py": {".py", ".pyi", ".pyx", ".pyw"},
    "md": {".md", ".markdown", ".mdx"},
    "json": {".json", ".jsonl", ".geojson"},
    "log": {".log"},
    "js": {".js", ".jsx", ".mjs", ".cjs"},
    "ts": {".ts", ".tsx"},
    "rust": {".rs"},
    "go": {".go"},
    "c": {".c", ".h"},
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".hh"},
    "java": {".java"},
    "rb": {".rb"},
    "php": {".php"},
    "html": {".html", ".htm"},
    "css": {".css", ".scss", ".sass", ".less"},
    "yaml": {".yaml", ".yml"},
    "toml": {".toml"},
    "sh": {".sh", ".bash", ".zsh"},
    "sql": {".sql"},
    "xml": {".xml"},
    "csv": {".csv", ".tsv"},
}

DEFAULT_WORKERS = 8

ANSI_RESET = "\x1b[0m"
ANSI_BOLD = "\x1b[1m"
ANSI_BLUE = "\x1b[94m"
ANSI_CYAN = "\x1b[5;96m"
ANSI_GREEN = "\x1b[32m"
ANSI_YELLOW = "\x1b[33m"
ANSI_MAGENTA = "\x1b[35m"

_PATH_PALETTE = (
    ANSI_CYAN,
    ANSI_GREEN,
    ANSI_YELLOW,
    ANSI_MAGENTA,
    "\x1b[96m",
    "\x1b[92m",
    "\x1b[93m",
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _stable_hash(s: str) -> int:
    """Deterministic FNV-1a-ish hash (avoids md5 import / availability)."""
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def color_for_path(path: str, enabled: bool) -> str:
    """Pick a stable per-directory color (item 22)."""
    if not enabled:
        return ""
    d = os.path.dirname(path) or "."
    return _PATH_PALETTE[_stable_hash(d) % len(_PATH_PALETTE)]


def normalize_extension(value: str) -> str:
    v = value.strip().lower().rstrip(".")
    if not v:
        return ""
    if not v.startswith("."):
        v = "." + v
    return v


def parse_extension_args(raw_exts: list[str] | None) -> set[str]:
    """Turn ['py,pyi', 'pyx'] into {'.py', '.pyi', '.pyx'}."""
    out: set[str] = set()
    if not raw_exts:
        return out
    for raw in raw_exts:
        for piece in raw.split(","):
            ext = normalize_extension(piece)
            if ext:
                out.add(ext)
    return out


def resolve_type_presets(types: list[str] | None) -> set[str]:
    """Expand -t/--type arguments into a union of extensions."""
    out: set[str] = set()
    if not types:
        return out
    for raw in types:
        for piece in raw.split(","):
            key = piece.strip().lower()
            if not key:
                continue
            if key not in TYPE_PRESETS:
                raise ValueError(
                    f"unknown type preset {key!r}; known presets: "
                    f"{', '.join(sorted(TYPE_PRESETS))}"
                )
            out |= TYPE_PRESETS[key]
    return out


def matches_any_glob(path: Path, patterns: list[str]) -> bool:
    name = path.name
    s = str(path)
    return any(fnmatch.fnmatch(s, p) or fnmatch.fnmatch(name, p) for p in patterns)


def _open_output(path: str | None) -> tuple[TextIO, bool]:
    if not path:
        return sys.stdout, False
    return open(path, "w", encoding="utf-8", newline=""), True


def _should_color(args: argparse.Namespace, is_stdout: bool) -> bool:
    if args.color == "never":
        return False
    if args.color == "always":
        return True
    if not is_stdout:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


# --------------------------------------------------------------------------- #
# Minimal .gitignore / .ignore support (item 9)
# --------------------------------------------------------------------------- #


class IgnoreMatcher:
    """Very small per-directory gitignore-style matcher.

    Handles: comments, negation (!), anchoring (/), directory-only (trailing /),
    and the common globs (*, ?, [], **).  Loading is lazy and cached per dir.
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[tuple[re.Pattern[str], bool, bool]]] = {}

    def _load(self, d: Path) -> list[tuple[re.Pattern[str], bool, bool]]:
        key = str(d)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        rules: list[tuple[re.Pattern[str], bool, bool]] = []
        for fname in (".gitignore", ".ignore"):
            f = d / fname
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for raw in text.splitlines():
                line = raw.rstrip()
                if not line or line.lstrip().startswith("#"):
                    continue
                if line.startswith("\\#") or line.startswith("\\!"):
                    line = line[1:]
                negated = line.startswith("!")
                if negated:
                    line = line[1:]
                dir_only = line.endswith("/")
                if dir_only:
                    line = line[:-1]
                anchored = line.startswith("/")
                if anchored:
                    line = line[1:]
                if not line:
                    continue
                try:
                    rx = re.compile(self._glob_to_regex(line, anchored))
                except re.error:
                    continue
                rules.append((rx, negated, dir_only))
        self._cache[key] = rules
        return rules

    @staticmethod
    def _glob_to_regex(pattern: str, anchored: bool) -> str:
        """Translate a gitignore glob into a regex over a relative path."""
        out: list[str] = [r"^" if anchored else r"(?:^|.*/)"]
        i, n = 0, len(pattern)
        while i < n:
            c = pattern[i]
            if c == "*":
                if i + 1 < n and pattern[i + 1] == "*":
                    i += 2
                    if i < n and pattern[i] == "/":
                        i += 1
                        out.append(r"(?:.*/)?")
                    else:
                        out.append(r".*")
                else:
                    out.append(r"[^/]*")
                    i += 1
            elif c == "?":
                out.append(r"[^/]")
                i += 1
            elif c == "[":
                j = i + 1
                if j < n and pattern[j] in "!^":
                    j += 1
                if j < n and pattern[j] == "]":
                    j += 1
                while j < n and pattern[j] != "]":
                    j += 1
                if j >= n:
                    out.append(re.escape(c))
                    i += 1
                else:
                    cls = pattern[i + 1 : j]
                    if cls.startswith("!"):
                        cls = "^" + cls[1:]
                    out.append("[" + cls + "]")
                    i = j + 1
            else:
                out.append(re.escape(c))
                i += 1
        out.append(r"(?:/.*)?$")
        return "".join(out)

    def is_ignored(self, path: Path, root: Path) -> bool:
        """True if `path` (below `root`) is excluded by any ancestor's rules."""
        try:
            rel = path.relative_to(root)
        except ValueError:
            return False
        parts = rel.parts
        # Walk the path prefix-by-prefix. If any prefix is ignored we bail.
        for i in range(1, len(parts) + 1):
            is_dir = i < len(parts)
            ignored = False
            for j in range(0, i):
                d = root if j == 0 else root / Path(*parts[:j])
                rel_from_d = Path(*parts[j:i]).as_posix()
                for rx, neg, dir_only in self._load(d):
                    if dir_only and not is_dir:
                        continue
                    if rx.search(rel_from_d):
                        ignored = not neg
            if ignored:
                return True
        return False


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

# A single output line is (lineno, text, is_match, highlight_spans).
OutputLine = tuple[int, str, bool, list[tuple[int, int]]]


@dataclass
class FileResult:
    """Returned by `worker`.  `groups` is a list of contiguous line runs."""

    path: str
    groups: list[list[OutputLine]] = field(default_factory=list)
    match_count: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #


def _walk_dir(
    root: Path,
    *,
    max_depth: int | None,
    follow_symlinks: bool,
    exclude_dirs: set[str],
    ignore_matcher: IgnoreMatcher | None,
    search_hidden: bool,
) -> Iterator[Path]:
    """Depth-first walk that yields regular files under `root`.

    Uses os.scandir for speed, tracks visited (st_dev, st_ino) pairs to
    prevent symlink cycles, and consults `ignore_matcher` if provided.
    """
    seen: set[tuple[int, int]] = set()
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for entry in entries:
            try:
                is_symlink = entry.is_symlink()
            except OSError:
                continue
            if is_symlink and not follow_symlinks:
                continue

            name = entry.name
            if not search_hidden and name.startswith("."):
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                is_file = entry.is_file(follow_symlinks=follow_symlinks)
            except OSError:
                continue

            if is_dir:
                if name in exclude_dirs or name in IGNORED_DIRS:
                    continue
                if max_depth is not None and depth + 1 > max_depth:
                    continue
                p = Path(entry.path)
                if ignore_matcher is not None and ignore_matcher.is_ignored(p, root):
                    continue
                if follow_symlinks:
                    try:
                        st = entry.stat(follow_symlinks=True)
                    except OSError:
                        continue
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                stack.append((p, depth + 1))
            elif is_file:
                p = Path(entry.path)
                if ignore_matcher is not None and ignore_matcher.is_ignored(p, root):
                    continue
                yield p


def get_files(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    exclude_dirs: set[str],
    search_hidden: bool,
    max_size: int,
    extensions: set[str],
    max_depth: int | None,
    follow_symlinks: bool,
    ignore_matcher: IgnoreMatcher | None,
) -> Iterator[Path]:
    """Yield files matching every filter."""

    def _post_filter(p: Path) -> bool:
        if extensions and p.suffix.lower() not in extensions:
            return False
        if max_size:
            try:
                if p.stat().st_size > max_size:
                    return False
            except OSError:
                return False
        if include_globs and not matches_any_glob(p, include_globs):
            return False
        if exclude_globs and matches_any_glob(p, exclude_globs):
            return False
        return True

    for p_str in paths:
        p = Path(p_str)
        if p.is_file():
            if _post_filter(p):
                yield p
            continue
        if not p.is_dir():
            continue
        for f in _walk_dir(
            p,
            max_depth=max_depth,
            follow_symlinks=follow_symlinks,
            exclude_dirs=exclude_dirs,
            ignore_matcher=ignore_matcher,
            search_hidden=search_hidden,
        ):
            if _post_filter(f):
                yield f


# --------------------------------------------------------------------------- #
# Search core
# --------------------------------------------------------------------------- #


def _spans_for_line(
    line: str,
    regex: re.Pattern[str] | None,
    fixed: str,
    ignore_case: bool,
) -> list[tuple[int, int]]:
    """Return all (start, end) matches of the pattern within a single line."""
    if regex is not None:
        return [(m.start(), m.end()) for m in regex.finditer(line)]
    if not fixed:
        return []
    hay = line.lower() if ignore_case else line
    needle = fixed.lower() if ignore_case else fixed
    spans: list[tuple[int, int]] = []
    start = 0
    L = max(1, len(needle))
    while True:
        idx = hay.find(needle, start)
        if idx == -1:
            break
        spans.append((idx, idx + len(needle)))
        start = idx + L
    return spans


def _apply_replace_line(
    line: str,
    matches: list[re.Match[str]],
    template: str,
) -> tuple[str, list[tuple[int, int]]]:
    """Apply `template` to every match in `line`.

    Returns (new_text, highlight_spans).  Backreferences (\\1, \\g<name>) are
    expanded via `re.Match.expand`.
    """
    if not matches:
        return line, []
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    out_len = 0
    for m in matches:
        prefix = line[pos : m.start()]
        parts.append(prefix)
        out_len += len(prefix)
        try:
            repl = m.expand(template)
        except re.error:
            repl = template
        spans.append((out_len, out_len + len(repl)))
        parts.append(repl)
        out_len += len(repl)
        pos = m.end()
    parts.append(line[pos:])
    return "".join(parts), spans


def _replace_fixed(text: str, needle: str, repl: str, ignore_case: bool) -> str:
    if not needle:
        return text
    if ignore_case:
        return re.sub(re.escape(needle), lambda _m: repl, text, flags=re.IGNORECASE)
    return text.replace(needle, repl)


def _build_groups(
    lines: list[str],
    match_lines: dict[int, tuple[str, list[tuple[int, int]]]],
    context_before: int,
    context_after: int,
) -> list[list[OutputLine]]:
    """Merge match lines + their context into non-overlapping groups."""
    context_set: set[int] = set()
    for lineno in match_lines:
        start = max(1, lineno - context_before)
        end = min(len(lines), lineno + context_after)
        for c in range(start, end + 1):
            context_set.add(c)

    groups: list[list[OutputLine]] = []
    current: list[OutputLine] = []
    prev: int | None = None
    for c in sorted(context_set):
        if prev is not None and c != prev + 1:
            groups.append(current)
            current = []
        if c in match_lines:
            text, spans = match_lines[c]
            current.append((c, text, True, spans))
        else:
            current.append((c, lines[c - 1], False, []))
        prev = c
    if current:
        groups.append(current)
    return groups


def _process_lines(
    rel_path: str,
    lines: list[str],
    regex: re.Pattern[str] | None,
    fixed: str,
    ignore_case: bool,
    invert: bool,
    context_before: int,
    context_after: int,
    max_count: int,
    replace: str | None,
    only_matching: bool,
) -> FileResult:
    """Line-by-line search path."""
    hits: list[tuple[int, list[tuple[int, int]]]] = []
    for idx, line in enumerate(lines):
        spans = _spans_for_line(line, regex, fixed, ignore_case)
        matched = bool(spans) != invert
        if not matched:
            continue
        if invert:
            spans = []
        hits.append((idx + 1, spans))
        if max_count and len(hits) >= max_count:
            break

    if not hits:
        return FileResult(path=rel_path)

    match_count = len(hits)

    # --only-matching: emit one output "line" per individual match.
    if only_matching:
        current: list[OutputLine] = []
        for lineno, spans in hits:
            line = lines[lineno - 1]
            if not spans:
                current.append((lineno, line, True, []))
                continue
            for s, e in spans:
                piece = line[s:e]
                if replace is not None and regex is not None:
                    m = next(
                        (
                            mm
                            for mm in regex.finditer(line)
                            if mm.start() == s and mm.end() == e
                        ),
                        None,
                    )
                    if m is not None:
                        try:
                            piece = m.expand(replace)
                        except re.error:
                            piece = replace
                elif replace is not None and regex is None:
                    piece = replace
                current.append((lineno, piece, True, [(0, len(piece))]))
        return FileResult(
            path=rel_path,
            groups=[current] if current else [],
            match_count=match_count,
        )

    # Build match lines (with --replace applied if requested).
    match_lines: dict[int, tuple[str, list[tuple[int, int]]]] = {}
    for lineno, spans in hits:
        text = lines[lineno - 1]
        if replace is not None and regex is not None:
            matches = list(regex.finditer(text))
            new_text, new_spans = _apply_replace_line(text, matches, replace)
            match_lines[lineno] = (new_text, new_spans)
        elif replace is not None and regex is None:
            new_text = _replace_fixed(text, fixed, replace, ignore_case)
            match_lines[lineno] = (new_text, [])
        else:
            match_lines[lineno] = (text, spans)

    groups = _build_groups(lines, match_lines, context_before, context_after)
    return FileResult(path=rel_path, groups=groups, match_count=match_count)


def _process_multiline(
    rel_path: str,
    text: str,
    regex: re.Pattern[str],
    context_before: int,
    context_after: int,
    max_count: int,
    replace: str | None,
) -> FileResult:
    """Whole-file regex search (DOTALL), for --multiline."""
    lines = text.splitlines()
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def to_line_idx(offset: int) -> int:
        return max(0, bisect.bisect_right(line_starts, offset) - 1)

    hits: dict[int, list[tuple[int, int]]] = {}
    order: list[int] = []
    for m in regex.finditer(text):
        if m.start() == m.end():
            continue
        ls = to_line_idx(m.start())
        le = to_line_idx(max(m.start(), m.end() - 1))
        for li in range(ls, le + 1):
            line_start = line_starts[li]
            line_text = lines[li] if li < len(lines) else ""
            span_start = max(0, m.start() - line_start)
            span_end = min(len(line_text), m.end() - line_start)
            if li not in hits:
                hits[li] = []
                order.append(li)
            if span_start < span_end:
                hits[li].append((span_start, span_end))
            else:
                hits[li].append((0, len(line_text)))
        if max_count and len(order) >= max_count:
            break

    if not order:
        return FileResult(path=rel_path)

    match_lines: dict[int, tuple[str, list[tuple[int, int]]]] = {}
    for li in order:
        line_text = lines[li]
        spans = hits[li]
        if replace is not None:
            new_text, new_spans = _replace_spans(line_text, spans, replace)
            match_lines[li + 1] = (new_text, new_spans)
        else:
            match_lines[li + 1] = (line_text, spans)

    groups = _build_groups(lines, match_lines, context_before, context_after)
    return FileResult(path=rel_path, groups=groups, match_count=len(order))


def _replace_spans(
    line: str,
    spans: list[tuple[int, int]],
    template: str,
) -> tuple[str, list[tuple[int, int]]]:
    """Replace each span in `line` with `template` (no backref expansion)."""
    if not spans:
        return line, []
    parts: list[str] = []
    new_spans: list[tuple[int, int]] = []
    pos = 0
    out_len = 0
    for s, e in sorted(spans):
        prefix = line[pos:s]
        parts.append(prefix)
        out_len += len(prefix)
        parts.append(template)
        new_spans.append((out_len, out_len + len(template)))
        out_len += len(template)
        pos = e
    parts.append(line[pos:])
    return "".join(parts), new_spans


# --------------------------------------------------------------------------- #
# Worker (runs in subprocess)
# --------------------------------------------------------------------------- #


def worker(job: dict[str, Any]) -> FileResult:
    """Search one file.  Inputs are plain data so pickling is trivial (item 24)."""
    path_str: str = job["path"]
    cwd_str: str = job["cwd"]
    regex_pattern = job["regex"]  # str | None
    fixed: str = job["fixed"]
    ignore_case: bool = job["ignore_case"]
    invert: bool = job["invert"]
    before: int = job["before"]
    after: int = job["after"]
    max_count: int = job["max_count"]
    multiline: bool = job["multiline"]
    encoding: str = job["encoding"]
    replace = job["replace"]  # str | None
    only_matching: bool = job["only_matching"]

    path = Path(path_str)
    cwd = Path(cwd_str)
    try:
        rel_path = str(path.relative_to(cwd))
    except ValueError:
        rel_path = path_str

    compiled: re.Pattern[str] | None = None
    if regex_pattern is not None:
        flags = re.MULTILINE
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.DOTALL
        try:
            compiled = re.compile(regex_pattern, flags)
        except re.error as ex:  # item 25: never propagate opaque errors
            return FileResult(path=rel_path, error=f"invalid regex: {ex}")

    # Cheap binary check (dh.is_binary may raise on odd files).
    try:
        if is_binary(path):
            return FileResult(path=rel_path)
    except Exception:
        pass

    try:
        with path.open(encoding=encoding, errors="replace", newline="") as fh:
            text = fh.read()
    except OSError as ex:
        return FileResult(path=rel_path, error=ex.strerror or str(ex))
    except Exception as ex:
        return FileResult(path=rel_path, error=f"{type(ex).__name__}: {ex}")

    try:
        if multiline and compiled is not None and not invert:
            return _process_multiline(
                rel_path,
                text,
                compiled,
                before,
                after,
                max_count,
                replace,
            )
        return _process_lines(
            rel_path,
            text.splitlines(),
            compiled,
            fixed,
            ignore_case,
            invert,
            before,
            after,
            max_count,
            replace,
            only_matching,
        )
    except re.error as ex:
        return FileResult(path=rel_path, error=f"regex error: {ex}")
    except Exception as ex:
        return FileResult(path=rel_path, error=f"{type(ex).__name__}: {ex}")


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #


def _colorize_line(line: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return line
    chars = list(line)
    for s, e in sorted(spans, key=lambda x: x[0], reverse=True):
        chars.insert(e, ANSI_RESET)
        chars.insert(s, ANSI_BLUE + ANSI_BOLD)
    return "".join(chars)


def _emit_path(path: str, out_fh: TextIO, color: bool) -> None:
    if color:
        print(f"{color_for_path(path, color)}{path}{ANSI_RESET}", file=out_fh)
    else:
        print(path, file=out_fh)


def emit_result(
    result: FileResult,
    args: argparse.Namespace,
    out_fh: TextIO,
    color: bool,
    heading: bool,
) -> None:
    """Render one file's results according to the active output mode."""
    # -l / --files-with-matches
    if args.files_with_matches:
        _emit_path(result.path, out_fh, color)
        return

    # -c / --count
    if args.count:
        print(f"{result.path}:{result.match_count}", file=out_fh)
        return

    # --json
    if args.json:
        for group in result.groups:
            for lineno, text, is_match, spans in group:
                if not is_match:
                    continue
                col = spans[0][0] + 1 if spans else 1
                print(
                    json.dumps(
                        {
                            "path": result.path,
                            "line": lineno,
                            "col": col,
                            "text": text,
                        },
                        ensure_ascii=False,
                    ),
                    file=out_fh,
                )
        return

    # Heading (ripgrep-style grouping)
    if heading:
        path_col = color_for_path(result.path, color)
        reset = ANSI_RESET if color else ""
        print(f"{path_col}{result.path}{reset}", file=out_fh)
        indent = "  "
    else:
        indent = ""

    first_group = True
    for group in result.groups:
        if not first_group:
            print("--", file=out_fh)
        first_group = False
        for lineno, text, is_match, spans in group:
            if is_match:
                body = _colorize_line(text, spans) if color and spans else text
            else:
                body = text

            # Prefix:  path:line:  for matches, path-line-  for context.
            sep = ":" if is_match else "-"
            if heading:
                prefix = indent
            else:
                pcol = color_for_path(result.path, color)
                reset = ANSI_RESET if color else ""
                prefix = f"{pcol}{result.path}{reset}{sep}"

            if args.line_number:
                if color:
                    print(
                        f"{prefix}{ANSI_GREEN}{lineno}{ANSI_RESET}{sep}{body}",
                        file=out_fh,
                    )
                else:
                    print(f"{prefix}{lineno}{sep}{body}", file=out_fh)
            else:
                print(f"{prefix}{body}", file=out_fh)


# --------------------------------------------------------------------------- #
# Argument parser
# --------------------------------------------------------------------------- #


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pyrg",
        description="ripgrep-like recursive search in Python",
    )

    # ---- Pattern / filtering by type ------------------------------------- #
    p.add_argument("pattern", nargs="?", help="Regex pattern (or use -r/--regexp)")
    p.add_argument(
        "-r",
        "--regexp",
        dest="pattern_e",
        help="Pattern (alternative to the positional argument)",
    )
    p.add_argument(
        "-e",
        "--extension",
        dest="extensions",
        action="append",
        metavar="EXT",
        help="Only search files with the given extension(s). "
        "Accepts dotless, dotted and comma-separated values.",
    )
    p.add_argument(
        "-t",
        "--type",
        dest="types",
        action="append",
        metavar="TYPE",
        help=f"Only search files matching a curated type preset. "
        f"Known: {', '.join(sorted(TYPE_PRESETS))}",
    )

    # ---- Matching -------------------------------------------------------- #
    p.add_argument("-i", "--ignore-case", action="store_true")
    p.add_argument("-F", "--fixed-strings", action="store_true")
    p.add_argument("-v", "--invert-match", action="store_true")
    p.add_argument(
        "--multiline",
        action="store_true",
        help="Allow the pattern to span multiple lines (DOTALL)",
    )

    # ---- Replacement / only-matching (item 11, 12) ----------------------- #
    p.add_argument(
        "-o",
        "--only-matching",
        action="store_true",
        help="Print only the matched (or replaced) parts of lines",
    )
    p.add_argument(
        "--replace",
        metavar="REPL",
        help="Replace matches with REPL in output (\\1 backrefs). "
        "Does NOT modify files.",
    )

    # ---- Output ---------------------------------------------------------- #
    p.add_argument("-n", "--line-number", action="store_true", default=True)
    p.add_argument("--no-line-number", dest="line_number", action="store_false")
    p.add_argument("-l", "--files-with-matches", action="store_true")
    p.add_argument("--files-without-match", action="store_true")
    p.add_argument("-c", "--count", action="store_true")
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress output; exit status indicates match",
    )
    p.add_argument("--json", action="store_true", help="Emit one JSON object per match")
    p.add_argument("--heading", action="store_true", default=None)
    p.add_argument("--no-heading", dest="heading", action="store_false")
    p.add_argument("--sort", choices=("path", "none"), default="none")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    p.add_argument("--no-color", dest="color", action="store_const", const="never")
    p.add_argument(
        "--out-file",
        dest="out_file",
        metavar="FILE",
        default=None,
        help="Write matches to FILE instead of stdout",
    )

    # ---- Context (item 2) ------------------------------------------------ #
    p.add_argument("-A", "--after-context", type=int, default=0, metavar="N")
    p.add_argument("-B", "--before-context", type=int, default=0, metavar="N")
    p.add_argument(
        "-C",
        "--context",
        type=int,
        default=None,
        metavar="N",
        help="Shorthand for -A N -B N",
    )

    # ---- File filtering -------------------------------------------------- #
    p.add_argument("--hidden", action="store_true")
    p.add_argument("-g", "--glob", action="append")
    p.add_argument("-x", "--exclude", action="append")
    p.add_argument("--exclude-dir", action="append", default=[], metavar="NAME")
    p.add_argument("--max-depth", type=int, default=None, metavar="N")
    p.add_argument(
        "--max-filesize",
        type=int,
        default=10_000_000,
        metavar="BYTES",
        help="Skip files larger than BYTES",
    )
    p.add_argument(
        "-M",
        "--max-count",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N matches per file",
    )
    p.add_argument(
        "--no-ignore",
        action="store_true",
        help="Do not honour .gitignore / .ignore files",
    )
    p.add_argument(
        "-L",
        "--follow",
        action="store_true",
        help="Follow symlinks (with cycle detection)",
    )
    p.add_argument("--encoding", default="utf-8", metavar="ENC")

    # ---- Modes / misc ---------------------------------------------------- #
    p.add_argument(
        "--files",
        action="store_true",
        help="List files that would be searched, then exit",
    )
    p.add_argument(
        "--stats", action="store_true", help="Print a summary to stderr at the end"
    )
    p.add_argument(
        "--no-messages", action="store_true", help="Suppress per-file error reporting"
    )
    p.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help="Number of worker processes",
    )

    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to search (default: .)",
    )
    return p


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def _collect_files(args: argparse.Namespace) -> list[Path]:
    """Shared file-discovery path used by both --files and normal search."""
    extensions = parse_extension_args(args.extensions)
    extensions |= resolve_type_presets(args.types)

    ignore_matcher = None if args.no_ignore else IgnoreMatcher()
    exclude_dirs = set(args.exclude_dir or [])

    return list(
        get_files(
            paths=args.paths,
            include_globs=args.glob or [],
            exclude_globs=args.exclude or [],
            exclude_dirs=exclude_dirs,
            search_hidden=args.hidden,
            max_size=args.max_filesize,
            extensions=extensions,
            max_depth=args.max_depth,
            follow_symlinks=args.follow,
            ignore_matcher=ignore_matcher,
        )
    )


def _run_files_mode(args: argparse.Namespace, cwd: Path) -> int:
    files = _collect_files(args)
    if args.sort == "path":
        files.sort(key=lambda p: str(p))
    out_fh, should_close = _open_output(args.out_file)
    try:
        for f in files:
            try:
                rel = f.relative_to(cwd)
            except ValueError:
                rel = f
            print(str(rel), file=out_fh)
    finally:
        if should_close:
            out_fh.close()
    return 0


def _search_quiet(
    files: list[Path],
    cwd: Path,
    regex_pattern: str | None,
    fixed: str,
    args: argparse.Namespace,
) -> bool:
    """-q/--quiet: short-circuit as soon as we find anything."""
    jobs = [
        {
            "path": str(p),
            "cwd": str(cwd),
            "regex": regex_pattern,
            "fixed": fixed,
            "ignore_case": args.ignore_case,
            "invert": args.invert_match,
            "before": 0,
            "after": 0,
            "max_count": 1,
            "multiline": args.multiline and not args.invert_match,
            "encoding": args.encoding,
            "replace": None,
            "only_matching": False,
        }
        for p in files
    ]

    if args.workers <= 1:
        return any(worker(j).match_count for j in jobs)

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(worker, j) for j in jobs]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:
                continue
            if r.match_count:
                for f in futures:
                    f.cancel()
                return True
    return False


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    cwd = Path.cwd()
    args = build_argparser().parse_args(argv)

    # -C is a shorthand for -A N -B N (item 2).
    if args.context is not None:
        args.after_context = args.context
        args.before_context = args.context

    # --files short-circuits everything else (item 10).
    if args.files:
        return _run_files_mode(args, cwd)

    pattern = args.pattern_e or args.pattern
    if not pattern:
        print(
            "No pattern provided. Use positional PATTERN or -r/--regexp PATTERN.",
            file=sys.stderr,
        )
        return 2

    # Compile/validate once in main for a fast failure path.
    regex_pattern: str | None
    fixed: str
    if args.fixed_strings:
        regex_pattern, fixed = None, pattern
    else:
        regex_pattern, fixed = pattern, ""
        flags = re.MULTILINE
        if args.ignore_case:
            flags |= re.IGNORECASE
        if args.multiline:
            flags |= re.DOTALL
        try:
            re.compile(pattern, flags)
        except re.error as ex:
            print(f"Invalid regex: {ex}", file=sys.stderr)
            return 2

    # File discovery ------------------------------------------------------- #
    try:
        files = _collect_files(args)
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 2

    if args.sort == "path":
        files.sort(key=lambda p: str(p))

    # If we have no candidates, distinguish "no files searched" from
    # "no matches" by warning on stderr and still returning 1 (item 26).
    if not files:
        if not args.no_messages:
            print("pyrg: no files matched the search filters", file=sys.stderr)
        return 1

    # Output setup --------------------------------------------------------- #
    out_fh, should_close = _open_output(args.out_file)
    color = _should_color(args, out_fh is sys.stdout) and not args.json
    heading = args.heading if args.heading is not None else color

    t0 = time.monotonic()

    # --quiet -------------------------------------------------------------- #
    if args.quiet:
        try:
            any_match = _search_quiet(files, cwd, regex_pattern, fixed, args)
        finally:
            if should_close:
                out_fh.close()
        return 0 if any_match else 1

    # Normal search -------------------------------------------------------- #
    jobs = [
        {
            "path": str(p),
            "cwd": str(cwd),
            "regex": regex_pattern,
            "fixed": fixed,
            "ignore_case": args.ignore_case,
            "invert": args.invert_match,
            "before": args.before_context,
            "after": args.after_context,
            "max_count": args.max_count,
            "multiline": args.multiline and not args.invert_match,
            "encoding": args.encoding,
            "replace": args.replace,
            "only_matching": args.only_matching,
        }
        for p in files
    ]

    files_searched = 0
    files_matched = 0
    files_errored = 0
    total_matches = 0
    any_match = False

    def _consume(results: Iterator[FileResult]) -> None:
        nonlocal files_searched, files_matched, files_errored, total_matches, any_match
        for result in results:
            if result.error:
                files_errored += 1
                if not args.no_messages:
                    print(f"{result.path}: {result.error}", file=sys.stderr)
                continue
            files_searched += 1
            if result.match_count:
                any_match = True
                files_matched += 1
                total_matches += result.match_count
                emit_result(result, args, out_fh, color, heading)
            elif args.files_without_match:
                _emit_path(result.path, out_fh, color)

    try:
        if args.workers <= 1:
            _consume(worker(j) for j in jobs)
        else:
            # ProcessPoolExecutor streams completions in arrival order (item 23).
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                futures = [ex.submit(worker, j) for j in jobs]

                def _gen() -> Iterator[FileResult]:
                    for fut in as_completed(futures):
                        try:
                            yield fut.result()
                        except Exception as exc:  # pragma: no cover
                            yield FileResult(path="<worker>", error=str(exc))

                _consume(_gen())
    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)
        return 130
    finally:
        if should_close:
            out_fh.close()
            if args.out_file:
                print(f"Results written to: {args.out_file}", file=sys.stderr)

    # --stats (item 4) ----------------------------------------------------- #
    elapsed = time.monotonic() - t0
    if args.stats:
        parts = [
            f"{files_searched} files searched",
            f"{files_matched} matched",
            f"{total_matches} matches",
            f"{elapsed:.2f}s",
        ]
        if files_errored:
            parts.append(f"{files_errored} errors")
        print(", ".join(parts), file=sys.stderr)

    return 0 if any_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
