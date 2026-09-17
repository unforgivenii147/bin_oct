#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path

import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

WORKERS = 8
TYPECRIPT_EXTENSIONS = frozenset({".ts", ".tsx", ".mts", ".cts"})
TSX_EXTENSIONS = frozenset({".tsx"})


def make_language(language_capsule) -> Language:
    try:
        return Language(language_capsule)
    except TypeError:
        return language_capsule


def make_parser(is_tsx: bool) -> Parser:
    language_factory = (
        tstypescript.language_tsx if is_tsx else tstypescript.language_typescript
    )
    language = make_language(language_factory())
    parser = Parser()
    try:
        parser.language = language
    except AttributeError:
        parser.set_language(language)
    return parser


def is_typescript_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TYPECRIPT_EXTENSIONS


def iter_typescript_files(inputs: Iterable[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for raw_input in inputs:
        path = Path(raw_input)
        try:
            if path.is_symlink():
                print(f"warning: skipping symlink: {path}", file=sys.stderr)
                continue
            if path.is_file():
                candidates: Iterable[Path] = (path,)
            elif path.is_dir():
                candidates = (
                    child
                    for child in path.rglob("*")
                    if not child.is_symlink() and is_typescript_file(child)
                )
            else:
                print(f"warning: path not found: {path}", file=sys.stderr)
                continue
            for candidate in candidates:
                if not is_typescript_file(candidate):
                    continue
                try:
                    identity = candidate.resolve()
                except OSError:
                    identity = candidate.absolute()
                if identity not in seen:
                    seen.add(identity)
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
    output = bytearray()
    previous_end = 0
    for start, end in ranges:
        output.extend(source[previous_end:start])
        output.extend(
            byte for byte in source[start:end] if byte == ord("\n") or byte == ord("\r")
        )
        previous_end = end
    output.extend(source[previous_end:])
    return bytes(output)


def write_in_place(path: Path, content: bytes) -> None:
    stat_result = path.stat()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, stat_result.st_mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def process_file(path_text: str) -> tuple[str, int, str | None]:
    path = Path(path_text)
    try:
        source = path.read_bytes()
        parser = make_parser(path.suffix.lower() in TSX_EXTENSIONS)
        tree = parser.parse(source)
        ranges: list[tuple[int, int]] = []
        collect_comment_ranges(tree.root_node, ranges)
        if not ranges:
            return str(path), 0, None
        updated = remove_comment_ranges(source, ranges)
        if updated != source:
            write_in_place(path, updated)
        return str(path), len(ranges), None
    except (OSError, ValueError, TypeError) as exc:
        return str(path), 0, str(exc)


def main() -> int:
    inputs = sys.argv[1:] or ["."]
    files = list(iter_typescript_files(inputs))
    if not files:
        print("No TypeScript files found.", file=sys.stderr)
        return 0
    changed_files = 0
    total_comments = 0
    failures = 0
    with Pool(processes=WORKERS) as pool:
        jobs = [pool.apply_async(process_file, (str(path),)) for path in files]
        for job in jobs:
            path, removed_count, error = job.get()
            if error is not None:
                failures += 1
                print(f"error: {path}: {error}", file=sys.stderr)
                continue
            if removed_count:
                changed_files += 1
                total_comments += removed_count
                print(f"{path}: removed {removed_count} comment(s)")
    print(
        f"\nFiles scanned: {len(files)}"
        f"\nChanged files: {changed_files}"
        f"\nComments removed: {total_comments}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
