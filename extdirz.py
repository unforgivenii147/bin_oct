#!/data/data/com.termux/files/home/.local/bin/python
"""Report file extensions and/or top-level directories of the CWD.

Modes
-----
  -e / --ext    recursive per-extension file histogram
  -d / --dirs   top-level directories of the CWD (recursive sizes with -s)
  -s / --size   append a total-size column to whichever mode(s) are active

Default behaviour (no -e / -d): both sections are shown.
Passing exactly one flag selects only that section; passing both shows both.

Speed notes
-----------
* A single traversal of the tree feeds both modes when both are requested.
* Directory names alone (``-d`` without ``-s``) skip the tree walk entirely.
* ``os.scandir`` + an explicit LIFO stack replaces ``os.walk``/recursion:
  DirEntry caches its own type / size info (one stat at most per file), and
  symlinks are filtered for free on POSIX via ``d_type``.
* ``Path(...).suffix`` is replaced by an inline suffix extractor so we do not
  allocate a ``Path`` object per file.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _suffix(name: str) -> str:
    """Return the file extension, matching ``Path(name).suffix`` semantics.

    Implemented inline (not via ``Path``) to avoid building a Path per file.
    Leading dots (``.bashrc``) and trailing dots (``file.``) do not count as
    extensions.
    """
    i = name.rfind(".")
    return name[i:] if 0 < i < len(name) - 1 else ""


def human_size(num_bytes: int) -> str:
    """Return a compact human-readable representation of *num_bytes*."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{int(size)}B" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024


# --------------------------------------------------------------------------- #
# Filesystem traversal
# --------------------------------------------------------------------------- #
def walk_files(root: Path):
    """Yield ``(DirEntry, top_level_name)`` for every regular file under *root*.

    - Symlinks (files or directories) are skipped to prevent cycles and
      double-counting.
    - Directories named ``.git`` are pruned, so the whole subtree is skipped.
    - ``top_level_name`` is the name of the first-level subdirectory of
      *root* containing the file, or ``None`` when the file sits directly in
      *root*.  This lets callers bucket files per top-level directory
      without a second traversal.

    Traversal is depth-first using an explicit LIFO stack plus ``os.scandir``:
    no tuple allocation per directory (unlike ``os.walk``) and each
    ``DirEntry`` caches its own stat, so at most one ``stat`` call is made
    per file even when both an extension size and a directory size are
    needed.
    """
    stack: list[tuple[str, str | None]] = [(str(root), None)]
    while stack:
        dir_path, top = stack.pop()
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    # Prune version-control metadata entirely.
                    if entry.name == ".git":
                        continue
                    # Skip symlinks (cheap on POSIX via d_type).
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        yield entry, top
                    elif entry.is_dir(follow_symlinks=False):
                        # Only the first level under root names the bucket.
                        child_top = top if top is not None else entry.name
                        stack.append((entry.path, child_top))
        except OSError:
            # Unreadable directory: skip rather than abort the entire run.
            continue


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Report file extensions and/or top-level directories in the CWD."
    )
    parser.add_argument(
        "-e",
        "--ext",
        action="store_true",
        help="show recursive per-extension file counts (default when no mode chosen)",
    )
    parser.add_argument(
        "-d",
        "--dirs",
        action="store_true",
        help="show top-level directories of the CWD (default when no mode chosen)",
    )
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="add a total-size column to the active mode(s)",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def report_extensions(ext_counts: Counter, ext_sizes: Counter, with_size: bool) -> None:
    """Print the per-extension histogram."""
    if not ext_counts:
        print("No files found.")
        return

    # Column widths for aligned output.
    max_ext_len = max(len(ext) for ext in ext_counts)
    max_count_len = max(len(str(c)) for c in ext_counts.values())

    # Pre-format sizes only when requested.
    formatted_sizes: dict[str, str] = {}
    max_size_len = 0
    if with_size:
        formatted_sizes = {ext: human_size(ext_sizes.get(ext, 0)) for ext in ext_counts}
        max_size_len = max(len(s) for s in formatted_sizes.values())

    print("extensions found:")
    for ext, count in sorted(ext_counts.items()):
        line = f" {ext:<{max_ext_len}}  {count:>{max_count_len}}"
        if with_size:
            line += f"  {formatted_sizes[ext]:>{max_size_len}}"
        print(line)


def report_directories(
    dir_names: list[str], dir_sizes: Counter, with_size: bool
) -> None:
    """Print the top-level directory listing and the total count."""
    # Column width for the size column.
    formatted_sizes: dict[str, str] = {}
    max_size_len = 0
    if with_size and dir_names:
        formatted_sizes = {n: human_size(dir_sizes.get(n, 0)) for n in dir_names}
        max_size_len = max(len(s) for s in formatted_sizes.values())

    for name in dir_names:
        line = f"  -  {name}"
        if with_size:
            line += f"  {formatted_sizes[name]:>{max_size_len}}"
        print(line)

    total_line = f"total: {len(dir_names)} dirs"
    if with_size:
        total_line += f"  {human_size(sum(dir_sizes.values()))}"
    print(total_line)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> None:
    args = parse_args(argv)
    cwd = Path.cwd()

    # Default when neither flag is supplied: show both sections.
    show_ext = args.ext or not args.dirs
    show_dirs = args.dirs or not args.ext
    show_both = show_ext and show_dirs

    # A tree walk is only needed for:
    #   * extension mode (counts every file), or
    #   * directory mode with -s (needs recursive directory sizes).
    # A plain "-d" without -s is answered from a single scandir of the CWD.
    need_walk = show_ext or (show_dirs and args.size)

    ext_counts: Counter[str] = Counter()
    ext_sizes: Counter[str] = Counter()
    dir_sizes: Counter[str] = Counter()

    # ----------------------------------------------------------------------- #
    # Single pass over the tree, gathering whatever both modes need.
    # ----------------------------------------------------------------------- #
    if need_walk:
        for entry, top in walk_files(cwd):
            # --- Extension accounting (all files, no stat needed) ---------- #
            ext: str | None = None
            if show_ext:
                ext = _suffix(entry.name) or ".no_ext"
                ext_counts[ext] += 1

            # --- Size accounting (only when -s and we have a target) ------ #
            want_ext_size = args.size and show_ext
            want_dir_size = args.size and show_dirs and top is not None

            if want_ext_size or want_dir_size:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    # Unreadable file: still counted for extensions, but no
                    # size contribution anywhere.
                    continue
                if want_ext_size:
                    ext_sizes[ext] += size
                if want_dir_size:
                    dir_sizes[top] += size

    # ----------------------------------------------------------------------- #
    # Top-level directory names (immediate-children scan of CWD).
    # ----------------------------------------------------------------------- #
    dir_names: list[str] = []
    if show_dirs:
        try:
            with os.scandir(cwd) as it:
                for entry in it:
                    if entry.name == ".git":
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        dir_names.append(entry.name)
        except OSError:
            pass
        dir_names.sort()

    # ----------------------------------------------------------------------- #
    # Output
    # ----------------------------------------------------------------------- #
    if show_ext:
        report_extensions(ext_counts, ext_sizes, args.size)

    if show_both:
        print()  # blank separator between the two sections

    if show_dirs:
        report_directories(dir_names, dir_sizes, args.size)


if __name__ == "__main__":
    main()
