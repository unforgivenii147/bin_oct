#!/data/data/com.termux/files/home/.local/bin/python
"""A parallelized CLI tool using tree-sitter to strip regular comments from Lua files in-place while preserving LDoc/LuaLS annotations (starting with '---'). It accepts paths or directories, processes files concurrently with multiprocessing.Pool.imap, logs output using loguru, skips logging un-modified files, and reports summary stats upon completion."""

import argparse
import multiprocessing as mp
from collections.abc import Iterator
from pathlib import Path

import tree_sitter_lua
from loguru import logger
from tree_sitter import Language, Node, Parser

LUA_LANGUAGE: Language = Language(tree_sitter_lua.language())
LUA_EXTS: set[str] = {".lua"}
_PARSER: Parser | None = None


def get_parser() -> Parser:
    """Initialize and return a single-instance tree-sitter Lua parser.

    Returns:
        Parser: The tree-sitter Lua parser instance.
    """
    global _PARSER
    if _PARSER is None:
        _PARSER = Parser(LUA_LANGUAGE)
    return _PARSER


def collect_comment_ranges(root: Node, content: bytes) -> list[tuple[int, int]]:
    """Traverse AST to collect byte ranges for standard Lua comments, preserving LDoc/LuaLS annotations.

    Args:
        root (Node): Root node of the tree-sitter syntax tree.
        content (bytes): Raw byte contents of the source file.

    Returns:
        list[tuple[int, int]]: List of (start_byte, end_byte) pairs to strip.
    """
    ranges: list[tuple[int, int]] = []
    stack: list[Node] = [root]
    while stack:
        node: Node = stack.pop()
        if node.type == "comment":
            text: bytes = content[node.start_byte : node.end_byte]
            # Preserve LDoc / LuaLS annotation comments starting with `---`
            if not text.startswith(b"---"):
                ranges.append((node.start_byte, node.end_byte))
            continue
        for child in reversed(node.children):
            stack.append(child)
    return ranges


def strip_comments(content: bytes) -> tuple[bytes, int]:
    """Parse Lua source bytes and remove normal comments while keeping doc annotations.

    Args:
        content (bytes): Source file raw content.

    Returns:
        tuple[bytes, int]: Stripped content bytes and the count of comments removed.
    """
    parser: Parser = get_parser()
    tree = parser.parse(content)
    ranges: list[tuple[int, int]] = collect_comment_ranges(tree.root_node, content)
    if not ranges:
        return content, 0
    ranges.sort(key=lambda r: r[0])
    out: bytearray = bytearray()
    last: int = 0
    for start, end in ranges:
        out.extend(content[last:start])
        last = end
    out.extend(content[last:])
    return bytes(out), len(ranges)


def process_file_worker(args: tuple[Path, Path]) -> tuple[str, int, str]:
    """Worker helper unpacking tuple arguments for multiprocessing.Pool.imap.

    Args:
        args (tuple[Path, Path]): Pair of (target_path, base_path).

    Returns:
        tuple[str, int, str]: Relative path string, count of comments removed, and error string if any.
    """
    path, base = args
    try:
        content: bytes = path.read_bytes()
        new_content, count = strip_comments(content)
        if new_content != content:
            path.write_bytes(new_content)
        try:
            rel: str = str(path.relative_to(base))
        except ValueError:
            rel = str(path)
        return rel, count, ""
    except Exception as exc:
        return str(path), 0, str(exc)


def iter_lua_files(paths: list[Path]) -> Iterator[Path]:
    """Yield unique Lua file paths from a list of files or directories.

    Args:
        paths (list[Path]): Input file or directory paths.

    Yields:
        Iterator[Path]: Resolved, unique Lua file paths.
    """
    seen: set[Path] = set()
    for p in paths:
        if p.is_file() and p.suffix.lower() in LUA_EXTS:
            rp: Path = p.resolve()
            if rp not in seen:
                seen.add(rp)
                yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*.lua")):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    yield f


def main() -> int:
    """Parse CLI options, execute parallel comment stripping using mp.Pool.imap, and report execution log.

    Returns:
        int: Exit status code (0 for success, 1 for error/empty).
    """
    ap = argparse.ArgumentParser(
        description="Remove comments from Lua files in place, preserving '---' annotations (tree-sitter powered)."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories. Defaults to current directory recursively.",
    )
    args: argparse.Namespace = ap.parse_args()
    inputs: list[Path] = list(args.paths) if args.paths else [Path(".")]
    files: list[Path] = list(iter_lua_files(inputs))
    if not files:
        logger.error("No Lua files to process.")
        return 1

    base: Path = Path.cwd()
    total_comments: int = 0
    files_changed: int = 0
    errors: int = 0

    # Fixed 8 workers pool
    tasks: list[tuple[Path, Path]] = [(p, base) for p in files]
    with mp.Pool(processes=8) as pool:
        for rel, count, err in pool.imap(process_file_worker, tasks):
            if err:
                errors += 1
                logger.error(f"{rel}: ERROR: {err}")
                continue
            total_comments += count
            if count > 0:
                files_changed += 1
                print(f"{rel}: {count} comment(s) removed")

    print(
        f"Summary: {files_changed}/{len(files)} file(s) changed, "
        f"{total_comments} comment(s) removed, {errors} error(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
