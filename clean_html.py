#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import contextlib
import multiprocessing as mp
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_css
import tree_sitter_html
import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

SUPPORTED_SUFFIXES: dict[str, str] = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
DEFAULT_WORKERS = 8
CHUNK_SIZE = 32


@dataclass(frozen=True, slots=True)
class FileResult:
    path: str
    changed: bool
    comments_removed: int
    error: str | None = None


def build_parser(language_name: str) -> Parser:
    language_factories = {
        "html": tree_sitter_html.language,
        "css": tree_sitter_css.language,
        "javascript": tree_sitter_javascript.language,
        "typescript": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
    }
    language = Language(language_factories[language_name]())
    try:
        return Parser(language)
    except TypeError:
        parser = Parser()
        parser.language = language
        return parser


def iter_nodes(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        children = current.children
        if children:
            stack.extend(reversed(children))


def comment_ranges(source: bytes, parser: Parser) -> list[tuple[int, int]]:
    tree = parser.parse(source)
    ranges: list[tuple[int, int]] = []
    for node in iter_nodes(tree.root_node):
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
    return ranges


def remove_ranges(
    source: bytes,
    ranges: Iterable[tuple[int, int]],
) -> tuple[bytes, int]:
    unique_ranges = sorted(set(ranges), reverse=True)
    if not unique_ranges:
        return source, 0
    output = source
    removed = 0
    for start, end in unique_ranges:
        if start < 0 or end < start or end > len(output):
            continue
        output = output[:start] + output[end:]
        removed += 1
    return output, removed


def script_language_from_attributes(tag_bytes: bytes) -> str | None:
    normalized = tag_bytes.lower()
    if b"type=" not in normalized and b"language=" not in normalized:
        return "javascript"
    for marker in (b"text/typescript", b"application/typescript", b"typescript"):
        if marker in normalized:
            return "typescript"
    for marker in (b"text/tsx", b"application/tsx"):
        if marker in normalized:
            return "tsx"
    unsupported_markers = (
        b"application/json",
        b"application/ld+json",
        b"importmap",
        b"speculationrules",
        b"text/template",
        b"text/x-template",
        b"text/plain",
        b"application/xml",
    )
    if any(marker in normalized for marker in unsupported_markers):
        return None
    javascript_markers = (
        b"javascript",
        b"ecmascript",
        b"module",
        b"text/jsx",
        b"application/jsx",
    )
    if any(marker in normalized for marker in javascript_markers):
        return "javascript"
    return None


def style_language_from_attributes(tag_bytes: bytes) -> str | None:
    normalized = tag_bytes.lower()
    unsupported_markers = (
        b"text/less",
        b"text/scss",
        b"text/sass",
        b"text/stylus",
        b"text/x-scss",
        b"text/x-sass",
    )
    if any(marker in normalized for marker in unsupported_markers):
        return None
    return "css"


def inline_content_ranges(
    html_source: bytes,
    html_parser: Parser,
) -> list[tuple[int, int, str]]:
    tree = html_parser.parse(html_source)
    ranges: list[tuple[int, int, str]] = []
    for node in iter_nodes(tree.root_node):
        if node.type != "element":
            continue
        start_tag = None
        raw_text = None
        for child in node.children:
            if child.type == "start_tag":
                start_tag = child
            elif child.type == "raw_text":
                raw_text = child
        if start_tag is None or raw_text is None:
            continue
        opening_tag = html_source[start_tag.start_byte : start_tag.end_byte].lower()
        if opening_tag.startswith(b"<script"):
            language = script_language_from_attributes(opening_tag)
        elif opening_tag.startswith(b"<style"):
            language = style_language_from_attributes(opening_tag)
        else:
            continue
        if language is not None and raw_text.start_byte < raw_text.end_byte:
            ranges.append((raw_text.start_byte, raw_text.end_byte, language))
    return ranges


def strip_html_comments(source: bytes, parsers: dict[str, Parser]) -> tuple[bytes, int]:
    html_parser = parsers["html"]
    html_ranges = comment_ranges(source, html_parser)
    embedded = inline_content_ranges(source, html_parser)
    replacements: list[tuple[int, int, bytes, int]] = []
    for start, end, language_name in embedded:
        content = source[start:end]
        embedded_ranges = comment_ranges(content, parsers[language_name])
        cleaned_content, removed_count = remove_ranges(content, embedded_ranges)
        if removed_count:
            replacements.append((start, end, cleaned_content, removed_count))
    result = source
    removed_total = 0
    for start, end, replacement, removed_count in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        result = result[:start] + replacement + result[end:]
        removed_total += removed_count
    html_ranges_after_embedded = comment_ranges(result, html_parser)
    result, html_removed = remove_ranges(result, html_ranges_after_embedded)
    return result, removed_total + html_removed


def detect_newline(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def atomic_write(path: Path, data: bytes) -> None:
    parent = path.parent
    temp_path = parent / f".{path.name}.strip-comments-{os.getpid()}.tmp"
    try:
        original_mode = path.stat().st_mode
    except OSError:
        original_mode = None
    try:
        with temp_path.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if original_mode is not None:
            os.chmod(temp_path, original_mode)
        os.replace(temp_path, path)
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)


def process_file(path_string: str, dry_run: bool) -> FileResult:
    path = Path(path_string)
    try:
        if not path.is_file():
            return FileResult(path_string, False, 0, "Not a regular file")
        suffix = path.suffix.lower()
        language_name = SUPPORTED_SUFFIXES.get(suffix)
        if language_name is None:
            return FileResult(path_string, False, 0, "Unsupported file extension")
        source = path.read_bytes()
        if not source:
            return FileResult(path_string, False, 0)
        parsers = {
            "html": build_parser("html"),
            "css": build_parser("css"),
            "javascript": build_parser("javascript"),
            "typescript": build_parser("typescript"),
            "tsx": build_parser("tsx"),
        }
        if language_name == "html":
            cleaned, comments_removed = strip_html_comments(source, parsers)
        else:
            ranges = comment_ranges(source, parsers[language_name])
            cleaned, comments_removed = remove_ranges(source, ranges)
        if comments_removed == 0 or cleaned == source:
            return FileResult(path_string, False, 0)
        if not dry_run:
            atomic_write(path, cleaned)
        return FileResult(path_string, True, comments_removed)
    except PermissionError as exc:
        return FileResult(path_string, False, 0, f"Permission denied: {exc}")
    except UnicodeError as exc:
        return FileResult(path_string, False, 0, f"Encoding error: {exc}")
    except OSError as exc:
        return FileResult(path_string, False, 0, f"Filesystem error: {exc}")
    except Exception as exc:
        return FileResult(
            path_string,
            False,
            0,
            f"{type(exc).__name__}: {exc}",
        )


def is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES


def collect_files(inputs: list[Path]) -> list[Path]:
    found: set[Path] = set()
    for input_path in inputs:
        try:
            if input_path.is_file():
                if is_supported_file(input_path):
                    found.add(input_path.resolve())
            elif input_path.is_dir():
                for candidate in input_path.rglob("*"):
                    try:
                        if is_supported_file(candidate):
                            found.add(candidate.resolve())
                    except OSError:
                        continue
            else:
                print(f"Warning: path does not exist: {input_path}", file=sys.stderr)
        except OSError as exc:
            print(f"Warning: unable to scan {input_path}: {exc}", file=sys.stderr)
    return sorted(found, key=lambda path: str(path))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strip comments from HTML, CSS, JavaScript, and TypeScript files."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process. Defaults to the current directory.",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Worker process count (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report proposed changes without modifying files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.workers < 1:
        print("Error: --workers must be at least 1.", file=sys.stderr)
        return 2
    inputs = args.paths if args.paths else [Path.cwd()]
    files = collect_files(inputs)
    if not files:
        print("No supported files found.")
        return 0
    action = "Would process" if args.dry_run else "Processing"
    print(f"{action} {len(files)} file(s) with {args.workers} worker(s)...")
    changed_files = 0
    removed_total = 0
    errors = 0
    context = mp.get_context("spawn")
    with context.Pool(processes=args.workers) as pool:
        pending = [
            pool.apply_async(process_file, (str(path), args.dry_run)) for path in files
        ]
        for result_handle in pending:
            try:
                result = result_handle.get()
            except Exception as exc:
                errors += 1
                print(
                    f"ERROR: Worker failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            if result.error:
                errors += 1
                print(f"ERROR: {result.path}: {result.error}", file=sys.stderr)
                continue
            if result.changed:
                changed_files += 1
                removed_total += result.comments_removed
                prefix = "WOULD UPDATE" if args.dry_run else "UPDATED"
                print(
                    f"{prefix}: {result.path} "
                    f"({result.comments_removed} comment(s) removed)"
                )
    print()
    print(
        f"Done. Changed files: {changed_files}; "
        f"comments removed: {removed_total}; errors: {errors}."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
