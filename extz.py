#!/data/data/com.termux/files/home/.local/bin/python
"""extz.py — Report recursive per-extension file counts in the CWD, optionally
with total sizes per extension, and a per-extension filename sample column.

Usage:
    python extz.py                # show per-extension file counts
    python extz.py -s            # show per-extension counts with total sizes
    python extz.py -f            # show filename samples (2 max, or all if <3)
    python extz.py -s -f        # both size and filename columns
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Iterator, Optional, Tuple

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def file_extension(name: str) -> str:
    """Return the file extension, matching ``Path(name).suffix`` semantics.



    Implemented inline (not via ``Path````) to avoid building a Path per file
    during the recursive walk, which matters when scanning tens of thousands
    of files.



    Leading dots (``.bashrc````)and trailing dots (``file.````)do not
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


def walk_files(root: Path) -> Iterator[Tuple[os.DirEntry, Optional[str]]]:
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

                        child_top_level = (
                            top_level if top_level is not None else entry.name
                        )
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
        Namespace with attributes: ``size``, ``filenames``.



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
    parser.add_argument(
        "-f",
        "--filenames",
        action="store_true",
        help=(
            "show filename samples per extension: all names if the group has "
            "fewer than 3 files, otherwise 2 names plus '...'"
        ),
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------


def _format_filename_sample(filenames: list[str], total_count: int) -> str:
    """Format the filename sample column for one extension group.



    Rules:
        - If the group has fewer than 3 files, show all filenames joined
          by ", ".
        - If the group has 3+ files, show the first 2 filenames joined
          by ", ", followed by "..." (the count column already shows how
          many more exist).

    Args:
        filenames: List of filenames in this group (unsorted).
        total_count: Total number of files in this group (== len(filenames)).

    Returns:
        Formatted string for the filename column.


    """
    if total_count < 3:
        return ", ".join(filenames)
    return ", ".join(filenames[:2]) + ", ..."


def print_extension_histogram(
    counts: dict[str, int],
    sizes: dict[str, int],
    filenames: dict[str, list[str]],
    show_size: bool,
    show_filenames: bool,
) -> None:
    """Print the per-extension histogram.



    Args:
        counts: Mapping of extension (or ``".no_ext"````) to file count.
        sizes: Mapping of extension to total size in bytes (only used
            when ``show_size`` is True).
        filenames: Mapping of extension to list of filenames (only used
            when ``show_filenames`` is True).
        show_size: Whether to include a total-size column.
        show_filenames: Whether to include a filename-sample column.



    """
    if not counts:
        print("No files found.")
        return

    # Column widths: extension column sized to longest extension name;
    # count column sized to largest count value; size column (if shown)
    # sized to longest formatted size string; filename column (if shown)
    # sized to longest formatted filename sample.

    ext_width = max(len(ext) for ext in counts)
    count_width = max(len(str(count)) for count in counts.values())
    size_strings: dict[str, str] = {}
    size_width = 0
    if show_size:
        size_strings = {ext: format_size(sizes.get(ext, 0)) for ext in counts}
        size_width = max(len(s) for s in size_strings.values())

    filename_strings: dict[str, str] = {}
    filename_width = 0
    if show_filenames:
        filename_strings = {
            ext: _format_filename_sample(filenames.get(ext, []), counts[ext])
            for ext in counts
        }
        filename_width = max(len(s) for s in filename_strings.values())

    print("extensions found:")
    for ext, count in sorted(counts.items()):
        line = f" {ext:<{ext_width}}  {count:>{count_width}}"
        if show_size:
            line += f"  {size_strings[ext]:>{size_width}}"
        if show_filenames:
            line += f"  {filename_strings[ext]:<{filename_width}}"
        print(line)

        # Special case: after the ".no_ext" row, print a separator line
        # to visually set it apart from the rest of the histogram. This only
        # happens when the ".no_ext" group exists (i.e. there are files with
        # no extension).

        if show_filenames and ext == ".no_ext":
            print(
                "-"
                * (
                    ext_width
                    + count_width
                    + (size_width + 2 if show_size else 0)
                    + (filename_width + 2 if show_filenames else 0)
                    + 4
                )
            )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    """Entry point: walk the CWD recursively, count files per extension,
    and optionally report total sizes and/or filename samples per extension.



    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]`` via
            ``argparse``).
    """
    args = parse_args(argv)
    root = Path.cwd()

    ext_counts: DefaultDict[str, int] = defaultdict(int)
    ext_sizes: DefaultDict[str, int] = defaultdict(int)
    ext_filenames: DefaultDict[str, list[str]] = defaultdict(list)

    for entry, _ in walk_files(root):
        ext = file_extension(entry.name) or ".no_ext"
        ext_counts[ext] += 1
        if args.size:
            try:
                file_size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            ext_sizes[ext] += file_size
        if args.filenames:
            ext_filenames[ext].append(entry.name)

    print_extension_histogram(
        dict(ext_counts),
        dict(ext_sizes),
        dict(ext_filenames),
        args.size,
        args.filenames,
    )


if __name__ == "__main__":
    main()
