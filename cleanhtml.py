#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any

try:
    import tree_sitter_css
    import tree_sitter_html
    import tree_sitter_javascript
    import tree_sitter_typescript
    from tree_sitter import Language, Parser
except ImportError as e:
    print(f"Error: Missing tree-sitter dependencies. {e}")
    print("Please install required packages:")
    print(
        "pip install tree-sitter tree-sitter-html tree-sitter-css tree-sitter-javascript tree-sitter-typescript"
    )
    sys.exit(1)
HTML_LANG = Language(tree_sitter_html.language())
CSS_LANG = Language(tree_sitter_css.language())
JS_LANG = Language(tree_sitter_javascript.language())
TS_LANG = Language(tree_sitter_typescript.language_typescript())


def _get_parser(lang: Language) -> Parser:
    parser = Parser()
    parser.language = lang
    return parser


HTML_PARSER = _get_parser(HTML_LANG)
CSS_PARSER = _get_parser(CSS_LANG)
JS_PARSER = _get_parser(JS_LANG)
TS_PARSER = _get_parser(TS_LANG)


def _find_comment_ranges(node, ranges: list[tuple[int, int]]) -> None:
    if node.type == "comment":
        ranges.append((node.start_byte, node.end_byte))
    for child in node.children:
        _find_comment_ranges(child, ranges)


def _apply_removals(content: bytes, ranges: list[tuple[int, int]]) -> bytes:
    if not ranges:
        return content
    result = bytearray()
    last_idx = 0
    for start, end in sorted(ranges):
        result.extend(content[last_idx:start])
        last_idx = end
    result.extend(content[last_idx:])
    return bytes(result)


def strip_comments_standard(content: bytes, parser: Parser) -> tuple[bytes, int]:
    tree = parser.parse(content)
    ranges = []
    _find_comment_ranges(tree.root_node, ranges)
    if not ranges:
        return content, 0
    return _apply_removals(content, ranges), len(ranges)


def strip_comments_html(content: bytes) -> tuple[bytes, int]:
    tree = HTML_PARSER.parse(content)
    modifications: list[tuple[int, int, bytes]] = []
    total_comments = 0

    def traverse(node) -> None:
        nonlocal total_comments
        if node.type == "comment":
            modifications.append((node.start_byte, node.end_byte, b""))
            total_comments += 1
        elif node.type in ("script_element", "style_element"):
            raw_text_node = next(
                (child for child in node.children if child.type == "raw_text"), None
            )
            if raw_text_node and raw_text_node.end_byte > raw_text_node.start_byte:
                inner_content = content[
                    raw_text_node.start_byte : raw_text_node.end_byte
                ]
                parser = JS_PARSER if node.type == "script_element" else CSS_PARSER
                inner_tree = parser.parse(inner_content)
                inner_ranges = []
                _find_comment_ranges(inner_tree.root_node, inner_ranges)
                if inner_ranges:
                    total_comments += len(inner_ranges)
                    cleaned_inner = _apply_removals(inner_content, inner_ranges)
                    modifications.append(
                        (
                            raw_text_node.start_byte,
                            raw_text_node.end_byte,
                            cleaned_inner,
                        )
                    )
        for child in node.children:
            traverse(child)

    traverse(tree.root_node)
    if not modifications:
        return content, 0
    modifications.sort(key=lambda x: x[0])
    result = bytearray()
    last_idx = 0
    for start, end, replacement in modifications:
        result.extend(content[last_idx:start])
        result.extend(replacement)
        last_idx = end
    result.extend(content[last_idx:])
    return bytes(result), total_comments


def process_file(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
    except Exception as e:
        return {
            "file": str(path),
            "error": str(e),
            "comments_removed": 0,
            "changed": False,
        }
    ext = path.suffix.lower()
    try:
        if ext == ".html":
            new_content, count = strip_comments_html(content)
        elif ext == ".css":
            new_content, count = strip_comments_standard(content, CSS_PARSER)
        elif ext == ".js":
            new_content, count = strip_comments_standard(content, JS_PARSER)
        elif ext == ".ts":
            new_content, count = strip_comments_standard(content, TS_PARSER)
        else:
            return {
                "file": str(path),
                "error": "Unsupported extension",
                "comments_removed": 0,
                "changed": False,
            }
    except Exception as e:
        return {
            "file": str(path),
            "error": f"Parsing error: {e}",
            "comments_removed": 0,
            "changed": False,
        }
    changed = new_content != content
    if changed:
        try:
            path.write_bytes(new_content)
        except Exception as e:
            return {
                "file": str(path),
                "error": f"Write error: {e}",
                "comments_removed": count,
                "changed": False,
            }
    return {
        "file": str(path),
        "comments_removed": count,
        "changed": changed,
        "error": None,
    }


def collect_files(paths: list[str]) -> list[Path]:
    extensions = {".html", ".css", ".js", ".ts"}
    files = set()
    if not paths:
        paths = ["."]
    for p in paths:
        path = Path(p).resolve()
        if path.is_file():
            if path.suffix.lower() in extensions:
                files.add(path)
        elif path.is_dir():
            files.update(
                f.resolve()
                for f in path.rglob("*")
                if f.is_file() and f.suffix.lower() in extensions
            )
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="Strip comments from HTML, CSS, JS, and TS files using tree-sitter."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process. Defaults to current directory.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=8,
        help="Number of multiprocessing workers (default: 8).",
    )
    args = parser.parse_args()
    files = collect_files(args.paths)
    if not files:
        print("No matching files found.")
        return
    print(f"Found {len(files)} files. Processing with {args.workers} workers...")
    total_comments = 0
    changed_files = 0
    errors = 0
    with Pool(processes=args.workers) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in files]
        for res in async_results:
            stats = res.get()
            if stats.get("error"):
                print(f"  [ERROR] {stats['file']}: {stats['error']}")
                errors += 1
            elif stats["changed"]:
                print(
                    f"  [UPDATED] {stats['file']} (Removed {stats['comments_removed']} comments)"
                )
                total_comments += stats["comments_removed"]
                changed_files += 1
            else:
                pass
    print("-" * 40)
    print(f"Processing complete.")
    print(f"Files changed: {changed_files}")
    print(f"Total comments removed: {total_comments}")
    if errors > 0:
        print(f"Errors encountered: {errors}")


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
