#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path

import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser

WORKERS = 8
JS_EXTENSIONS = frozenset({".js", ".mjs", ".cjs", ".jsx"})


def javascript_language() -> Language:
    try:
        return Language(tsjavascript.language())
    except TypeError:
        return tsjavascript.language()


def make_parser() -> Parser:
    parser = Parser()
    language = javascript_language()
    try:
        parser.language = language
    except AttributeError:
        parser.set_language(language)
    return parser


def is_javascript_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in JS_EXTENSIONS


def iter_javascript_files(inputs: Iterable[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw_path in inputs:
        path = Path(raw_path)
        try:
            if path.is_file():
                candidates = (path,)
            elif path.is_dir():
                candidates = (
                    child
                    for child in path.rglob("*")
                    if not child.is_symlink() and is_javascript_file(child)
                )
            else:
                print(
                    f"warning: not found or unsupported path: {path}", file=sys.stderr
                )
                continue
            for candidate in candidates:
                if not is_javascript_file(candidate):
                    continue
                try:
                    resolved = candidate.resolve()
                except OSError:
                    resolved = candidate.absolute()
                if resolved not in seen:
                    seen.add(resolved)
                    yield candidate
        except OSError as exc:
            print(f"warning: cannot scan {path}: {exc}", file=sys.stderr)


def collect_comment_ranges(node, ranges: list[tuple[int, int]]) -> None:
    if node.type == "comment":
        ranges.append((node.start_byte, node.end_byte))
        return
    for child in node.children:
        collect_comment_ranges(child, ranges)


def remove_comment_ranges(source: bytes, ranges: list[tuple[int, int]]) -> bytes:
    if not ranges:
        return source
    output = bytearray()
    previous_end = 0
    for start, end in ranges:
        output.extend(source[previous_end:start])
        comment = source[start:end]
        output.extend(byte for byte in comment if byte in (ord("\n"), ord("\r")))
        previous_end = end
    output.extend(source[previous_end:])
    return bytes(output)


def process_file(path_string: str) -> tuple[str, int, str | None]:
    path = Path(path_string)
    try:
        source = path.read_bytes()
        parser = make_parser()
        tree = parser.parse(source)
        ranges: list[tuple[int, int]] = []
        collect_comment_ranges(tree.root_node, ranges)
        if not ranges:
            return str(path), 0, None
        updated = remove_comment_ranges(source, ranges)
        if updated != source:
            with path.open("wb") as file:
                file.write(updated)
        return str(path), len(ranges), None
    except (OSError, UnicodeError, ValueError) as exc:
        return str(path), 0, str(exc)


def main() -> int:
    inputs = sys.argv[1:] or ["."]
    files = list(iter_javascript_files(inputs))
    if not files:
        print("No JavaScript files found.", file=sys.stderr)
        return 0
    changed_files = 0
    total_comments = 0
    failures = 0
    chunksize = max(1, len(files) // (WORKERS * 8))
    with Pool(processes=WORKERS) as pool:
        results = [pool.apply_async(process_file, (str(path),)) for path in files]
        for result in results:
            path, removed, error = result.get()
            if error is not None:
                failures += 1
                print(f"error: {path}: {error}", file=sys.stderr)
                continue
            if removed:
                changed_files += 1
                total_comments += removed
                print(f"{path}: removed {removed} comment(s)")
    print(
        f"\nChanged files: {changed_files}"
        f"\nComments removed: {total_comments}"
        f"\nFiles scanned: {len(files)}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
