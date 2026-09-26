#!/data/data/com.termux/files/home/.local/bin/python
"""extz.py — Report recursive per-extension file counts in the CWD, optionally
with total sizes per extension.



Usage:
    python extz.py                # show per-extension file counts
    python extz.py -s            # show per-extension counts with total sizes
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Iterator, Optional, Tuple

# --------------------------------------------------------------------------
# Shared helpers (duplicated from the original compressed script)
# --------------------------------------------------------------------------


def file_extension(name: str) -> str:
    """Return the file extension, matching ``Path(name).suffix`` semantics.



    Implemented inline (not via ``Path``) to avoid building a Path per file
    during the recursive walk, which matters when scanning tens of thousands
    of files.



    Leading dots (``.bashrc``)and trailing dots (``file.``)do not
    count as extensions, matching ``Path.suffix`` behavior:

    - ``Path(".bashrc").suffix`` -> ``""``
    - ``Path("file.").suffix`` -> ``""``
    - ``Path("archive.tar.gz").suffix`` -> ``".gz"``

    Args:
        name: File name (not a full path).

    Returns:
        The extension including the leading dot, or ``""`` if there is none.

    """
    dot_index = name.rfind(".")
    if 0 < dot_index < len(name) - 1:
        return name[dot_index:]
    return ""


def format_size(num_bytes: int) -> str:
    """Return a compact human-readable representation of *num_bytes*.

    Uses binary units (1024-based): B, KB, MB, GB, TB, PB. Values
    below 1024 bytes are shown as integers; larger values get one decimal
    place (e.g. ``"1.5MB"``).

    Args:
        num_bytes: Size in bytes (non-negative).

    Returns:
        Human-readable size string.

    """
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    # Unreachable: the loop always returns on the last iteration.


def walk_files(root: Path) -> Iterator[Tuple[os.DirEntry, Optional[str]]]]:
    """Yield ``(DirEntry, top_level_name)`` for every regular file under *root*.

    Traversal is depth-first using an explicit LIFO stack plus ``os.scandir``.
    This avoids the per-directory tuple allocation that ``os.walk`` performs,
    and each ``DirEntry`` caches its own stat result, so at most one ``stat``
    call is made per file even when both an extension size and a directory
    size are needed (the ``DirEntry.stat()`` result is cached internally by
    Python's ``os.scandir`` implementation).



    Args:
        root: Directory to walk recursively. 

    Yields:
        Tuples of ``(DirEntry, top_level_name)`` where ``top_level_name`` is
        the name of the first-level subdirectory of *root* containing the file,
        or ``None`` when the file sits directly in *root*. This lets callers
        bucket files per top-level directory without a second traversal. 



    Notes:
        - Symlinks (files or directories) are skipped to prevent cycles and
          double-counting. 

        - Directories named ``.git`` are pruned, so the whole subtree is
          skipped entirely. 

        - Unreadable directories (``OSError`` during ``scandir````) are silently
          skipped, matching the original script's behavior. 

    """
    # Stack of (path, top_level_name) pairs. top_level_name is None for
    # the root itself; for subdirectories it's the name of the first-level
    # subdirectory under root that contains them.



    stack: list[Tuple[str, Optional[str]]] = [(str(root), None)]

    while stack:
        current_path, top_level = stack.pop()
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if entry.name == ".git":
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        yield entry, top_level
                    elif entry.is_dir(follow_symlinks=False):
                        # Propagate top_level: if we're at the root, the first
                        # subdirectory's own name becomes the top_level for its
                        # contents; deeper subdirectories keep the same top_level.



                        child_top_level = top_level if top_level is not None else entry.name
                        stack.append((entry.path, child_top_level))
        except OSError:
            # Unreadable directory (permissions, vanished mid-scan, etc.):
            # skip it silently, matching the original behavior. 
            continue


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for extz.py.



    Returns:
        Namespace with attribute: ``size``.


    """
    parser = argparse.ArgumentParser(
        description="Report recursive per-extension file counts in the CWD.",
    )
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="show total size per extension",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------


def print_extension_histogram(
    counts: dict[str, int],
    sizes: dict[str, int],
    show_size: bool,
) -> None:
    """Print the per-extension histogram.



    Args:
        counts: Mapping of extension (or ``".no_ext"``) to file count. 
        sizes: Mapping of extension to total size in bytes (only used
            when ``show_size`` is True).
        show_size: Whether to include a total-size column. 

    """
    if not counts:
        print("No files found.")
        return

    # Column widths: extension column sized to longest extension name;
    # count column sized to largest count value; size column (if shown)
    # sized to longest formatted size string. 

    ext_width = max(len(ext) for ext in counts)
    count_width = max(len(str(count)) for count in counts.values())
    size_strings: dict[str, str] = {}
    size_width = 0
    if show_size:
        size_strings = {ext: format_size(sizes.get(ext, 0)) for ext in counts}
        size_width = max(len(s) for s in size_strings.values())

    print("extensions found:")
    for ext, count in sorted(counts.items()):
        line = f" {ext:<{ext_width}}  {count:>{count_width}}"
        if show_size:
            line += f"  {size_strings[ext]:>{size_width}}"
        print(line)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    """Entry point: walk the CWD recursively, count files per extension,
    and optionally report total sizes per extension.



    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]`` via
            ``argparse``).
    """
    args = parse_args(argv)
    root = Path.cwd()

    ext_counts: DefaultDict[str, int] = defaultdict(int)
    ext_sizes: DefaultDict[str, int] = defaultdict(int)

    for entry, _ in walk_files(root):
        ext = file_extension(entry.name) or ".no_ext"
        ext_counts[ext] += 1
        if args.size:
            try:
                file_size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            ext_sizes[ext] += file_size

    print_extension_histogram(dict(ext_counts), dict(ext_sizes), args.size)


if __name__ == "__main__":
    main()
