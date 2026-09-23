#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final, Optional

from dh import fsz

# Module-level cache for the tree-sitter parser. Each worker process
# builds its own parser lazily on first use (important under "fork").
_parser: Optional[Any] = None

# Fixed worker count; no CLI flag for this by design.
_WORKERS: Final[int] = 8

# Number of characters reserved for the filename column in the report.
_NAME_WIDTH: Final[int] = 50


def _get_parser() -> Any:
    """Return a lazily-initialized tree-sitter TOML parser for this process."""
    global _parser
    if _parser is None:
        import tree_sitter_toml as tstoml  # type: ignore[import-untyped]
        from tree_sitter import Language, Parser  # type: ignore[import-untyped]

        _parser = Parser(Language(tstoml.language()))
    return _parser


def remove_toml_comments(content: str) -> str:
    """Strip every TOML comment (and trailing whitespace before it) from *content*."""
    parser: Any = _get_parser()
    source: bytes = content.encode("utf-8")
    tree: Any = parser.parse(source)

    # Collect (start_byte, end_byte) for every `comment` node in the AST.
    ranges: list[tuple[int, int]] = []
    stack: list[Any] = [tree.root_node]
    while stack:
        node: Any = stack.pop()
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
        else:
            stack.extend(node.children)

    if not ranges:
        return content

    result: bytearray = bytearray(source)
    # Delete from the end backwards so earlier byte offsets remain valid.
    for start, end in sorted(ranges, reverse=True):
        s: int = start
        # Swallow spaces/tabs that immediately preceded the comment.
        while s > 0 and result[s - 1] in (0x20, 0x09):
            s -= 1
        del result[s:end]

    return result.decode("utf-8")


def process_file(path: Path) -> tuple[str, float, int, int]:
    """Rewrite *path* with comments stripped; return (name, ms, before, after)."""
    start_time: float = time.perf_counter()
    try:
        with open(path, encoding="utf-8") as f:
            content: str = f.read()
        before_size: int = len(content.encode("utf-8"))
        cleaned_content: str = remove_toml_comments(content)
        with open(path, "w", encoding="utf-8") as f:
            f.write(cleaned_content)
        after_size: int = len(cleaned_content.encode("utf-8"))
        time_taken: float = (time.perf_counter() - start_time) * 1000.0
        return (str(path), time_taken, before_size, after_size)
    except Exception as e:
        print(f"Error processing {path}: {e}", file=sys.stderr)
        time_taken = (time.perf_counter() - start_time) * 1000.0
        return (str(path), time_taken, 0, 0)


def collect_toml_files(paths: list[Path]) -> list[Path]:
    """Expand *paths* (files and/or directories) into a list of .toml files."""
    toml_files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() == ".toml":
                toml_files.append(path)
        elif path.is_dir():
            toml_files.extend(path.rglob("*.toml"))
    return toml_files


def main() -> int:
    """Entry point: collect .toml files, strip comments in a pool, print a report."""
    paths: list[Path]
    if len(sys.argv) > 1:
        paths = [Path(arg) for arg in sys.argv[1:]]
    else:
        paths = [Path.cwd()]

    toml_files: list[Path] = collect_toml_files(paths)
    if not toml_files:
        print("No .toml files found to process.")
        return 0

    print(f"Found {len(toml_files)} TOML file(s) to process...")
    print("-" * 40)
    print(
        f"{'Filename':<50} {'Time (ms)':<10} {'Before':<12} {'After':<12} {'Ratio':<8}"
    )
    print("-" * 40)

    results: list[tuple[str, float, int, int]] = []
    with Pool(processes=_WORKERS) as pool:
        for result in pool.imap_unordered(process_file, toml_files):
            results.append(result)
            filename, time_taken, before_size, after_size = result
            ratio: float = after_size / before_size * 100.0 if before_size > 0 else 0.0
            display_name: str = (
                filename
                if len(filename) <= _NAME_WIDTH - 2
                else "..." + filename[-(_NAME_WIDTH - 3) :]
            )
            print(
                f"{display_name:<{_NAME_WIDTH}} {time_taken:>8.2f}  "
                f"{fsz(before_size):<12} {fsz(after_size):<12} {ratio:>6.1f}%"
            )

    print("-" * 40)
    total_before: int = sum(r[2] for r in results)
    total_after: int = sum(r[3] for r in results)
    total_ratio: float = total_after / total_before * 100.0 if total_before > 0 else 0.0
    total_time: float = sum(r[1] for r in results)
    print(f"Total: {len(results)} file(s) processed in {total_time:.2f} ms")
    print(
        f"Size reduction: {fsz(total_before)} -> {fsz(total_after)} "
        f"({total_ratio:.1f}% of original)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
