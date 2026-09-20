#!/data/data/com.termux/files/home/.local/bin/python
"""
htmlstrip.py - unified HTML tag / meta tag remover.

Combines three standalone scripts into one CLI with three subcommands.

Original -> merged mapping
--------------------------
    remove_tag.py   ->  python htmlstrip.py tag  <tagname> [directory]
    rmeta.py        ->  python htmlstrip.py meta [directory]
    strip_tags.py   ->  python htmlstrip.py all  <file> [-w]

Examples
--------
    # Remove every <script> tag from .html/.txt under cwd (BeautifulSoup)
    python htmlstrip.py tag script
    python htmlstrip.py tag script ./public --extensions .html .htm .txt

    # Remove all <meta ...> tags from every .html file under ./site
    python htmlstrip.py meta ./site
    python htmlstrip.py meta ./site --pattern '<meta[^>]*name="author"[^>]*>'

    # Preview which lines would be stripped from one file (dry-run)
    python htmlstrip.py all index.html
    # Do it
    python htmlstrip.py all index.html -w

Dependencies:
    beautifulsoup4   (required for the 'tag' subcommand)
    Standard library (regex) is used for 'meta' and 'all'.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# Optional third-party import
# ---------------------------------------------------------------------------
try:
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]

    HAS_BS4 = True
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]
    HAS_BS4 = False

LOG = logging.getLogger("htmlstrip")

# ---------------------------------------------------------------------------
# Constants (all overridable via CLI)
# ---------------------------------------------------------------------------
DEFAULT_TAG_EXTS: tuple[str, ...] = (".html", ".txt")
DEFAULT_META_EXTS: tuple[str, ...] = (".html",)
DEFAULT_META_PATTERN: str = r"<meta[^>]*>"
DEFAULT_PRESERVE_MARKERS: tuple[str, ...] = ("<:", ">:")
ALL_TAGS_REGEX = re.compile(r"<[^>]*>")


# ===========================================================================
# Shared helpers
# ===========================================================================
def _read_text(path: Path) -> str:
    """Read text with utf-8 then latin-1 fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _iter_files(
    root: Path,
    extensions: Sequence[str],
) -> Iterable[Path]:
    """Yield files under `root` whose suffix matches one of `extensions`."""
    exts = tuple(
        e.lower() if e.startswith(".") else "." + e.lower() for e in extensions
    )
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            yield p


def _normalize_exts(raw: Sequence[str], default: Sequence[str]) -> list[str]:
    if not raw:
        return list(default)
    return [e.lower() if e.startswith(".") else "." + e.lower() for e in raw]


# ===========================================================================
# Subcommand: tag  (remove_tag.py)
# ===========================================================================
def _remove_tag_from_file(path: Path, tag: str) -> bool:
    """Remove all <tag> elements from `path` with BeautifulSoup.  True on write."""
    try:
        src = _read_text(path)
    except OSError as e:
        LOG.error("Cannot read %s: %s", path, e)
        return False

    try:
        soup = BeautifulSoup(src, "html.parser")
    except Exception as e:  # noqa: BLE001
        LOG.error("Parse failed for %s: %s", path, e)
        return False

    found = soup.find_all(tag)
    if not found:
        LOG.info("No <%s> found in %s", tag, path)
        return False
    for el in found:
        el.decompose()

    try:
        path.write_text(str(soup), encoding="utf-8")
    except OSError as e:
        LOG.error("Cannot write %s: %s", path, e)
        return False

    print(f"Removed <{tag}> from {path}")
    return True


def cmd_tag(args: argparse.Namespace) -> int:
    if not HAS_BS4:
        LOG.error(
            "The 'tag' subcommand requires beautifulsoup4 (pip install beautifulsoup4)."
        )
        return 2

    root = Path(args.directory)
    if not root.is_dir():
        LOG.error("Not a directory: %s", root)
        return 1

    exts = _normalize_exts(args.extensions, DEFAULT_TAG_EXTS)
    total = 0
    for f in _iter_files(root, exts):
        if _remove_tag_from_file(f, args.tagname):
            total += 1

    print(f"Done. Modified {total} file(s).")
    return 0


# ===========================================================================
# Subcommand: meta  (rmeta.py)
# ===========================================================================
_META_RX_CACHE: dict[str, re.Pattern[str]] = {}


def _meta_rx(pattern: str) -> re.Pattern[str]:
    if pattern not in _META_RX_CACHE:
        _META_RX_CACHE[pattern] = re.compile(pattern, re.IGNORECASE)
    return _META_RX_CACHE[pattern]


def _remove_meta_from_file(path: Path, pattern: str) -> Optional[bool]:
    """
    Remove `<meta ...>` tags via regex on the ORIGINAL text (formatting preserved).

    Returns True if written, False if nothing matched, None on error.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        LOG.error("Cannot read %s: %s", path, e)
        return None

    rx = _meta_rx(pattern)
    new_src = rx.sub("", src)

    if new_src == src:
        print(f"No meta tags found or removed in: {path}")
        return False

    try:
        path.write_text(new_src, encoding="utf-8")
    except OSError as e:
        LOG.error("Cannot write %s: %s", path, e)
        return None

    print(f"Removed meta tags from: {path}")
    return True


def cmd_meta(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    print(
        f"Starting to remove meta tags from HTML files in '{root}' "
        f"and its subdirectories...\n"
    )

    exts = _normalize_exts(args.extensions, DEFAULT_META_EXTS)
    total = 0
    for f in _iter_files(root, exts):
        if _remove_meta_from_file(f, args.pattern):
            total += 1

    print(f"\nFinished processing. Modified {total} file(s).")
    return 0


# ===========================================================================
# Subcommand: all  (strip_tags.py)
# ===========================================================================
def _strip_all_tags(
    source: str,
    preserve_markers: Sequence[str],
) -> tuple[str, list[str]]:
    """
    Strip every `<...>` tag from each line, EXCEPT lines containing a
    preserve-marker (kept verbatim).  Returns (new_source, removed_lines).
    """
    lines = source.split("\n")
    new_lines: list[str] = []
    removed: list[str] = []
    for line in lines:
        if any(marker in line for marker in preserve_markers):
            new_lines.append(line)
            continue
        cleaned = ALL_TAGS_REGEX.sub("", line)
        new_lines.append(cleaned)
        if cleaned != line:
            removed.append(line)
    return "\n".join(new_lines), removed


def cmd_all(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        LOG.error("Not a file: %s", path)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        LOG.error("Cannot read %s: %s", path, e)
        return 1

    markers = (
        list(args.preserve_marker)
        if args.preserve_marker
        else list(DEFAULT_PRESERVE_MARKERS)
    )
    new_source, removed = _strip_all_tags(source, markers)

    for line in removed:
        print(f"-{line}")

    if args.write:
        try:
            path.write_text(new_source, encoding="utf-8")
        except OSError as e:
            LOG.error("Cannot write %s: %s", path, e)
            return 1
        print(f"\nFile updated: {path}")
    else:
        print("\nFile not updated. Re-run with -w to write changes in place.")
    return 0


# ===========================================================================
# CLI
# ===========================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="htmlstrip.py",
        description="Unified HTML tag / meta tag remover.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- tag ----------------------------------------------------------------
    p = sub.add_parser(
        "tag", help="Remove a named tag using BeautifulSoup (remove_tag.py)."
    )
    p.add_argument("tagname", help="Tag to remove (e.g. script, style, iframe)")
    p.add_argument(
        "directory", nargs="?", default=".", help="Root directory (default: .)"
    )
    p.add_argument(
        "--extensions",
        nargs="*",
        default=list(DEFAULT_TAG_EXTS),
        help=f"File extensions to process (default: {' '.join(DEFAULT_TAG_EXTS)})",
    )
    p.set_defaults(func=cmd_tag)

    # -- meta ---------------------------------------------------------------
    p = sub.add_parser("meta", help="Remove <meta ...> tags via regex (rmeta.py).")
    p.add_argument(
        "directory", nargs="?", default=".", help="Root directory (default: .)"
    )
    p.add_argument(
        "--pattern",
        default=DEFAULT_META_PATTERN,
        help=f"Regex matching tags to remove (default: {DEFAULT_META_PATTERN})",
    )
    p.add_argument(
        "--extensions",
        nargs="*",
        default=list(DEFAULT_META_EXTS),
        help=f"File extensions to process (default: {' '.join(DEFAULT_META_EXTS)})",
    )
    p.set_defaults(func=cmd_meta)

    # -- all ----------------------------------------------------------------
    p = sub.add_parser(
        "all", help="Strip every <...> tag from one file (strip_tags.py)."
    )
    p.add_argument("file", help="File to process")
    p.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write changes in place (default: dry-run)",
    )
    p.add_argument(
        "--preserve-marker",
        action="append",
        default=None,
        help=(
            "Substring; any line containing it is kept verbatim "
            "(repeatable; default: '<:' and '>:')"
        ),
    )
    p.set_defaults(func=cmd_all)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        return args.func(args)
    except KeyboardInterrupt:
        LOG.warning("Operation cancelled by user")
        return 130
    except Exception as e:  # noqa: BLE001
        LOG.error("Unexpected error: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
