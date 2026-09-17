#!/data/data/com.termux/files/home/.local/bin/python
"""
Duplicate File Finder and Remover

Generate a Python script that scans a directory (recursively by default) for duplicate files
by content, using a multi-phase approach (size grouping -> quick hash -> full hash) with
multiprocessing.Pool.apply_async for parallelism. The script should:
- Skip .git directories, symlinks (by default), and files smaller than --min-size.
- Use xxhash.xxh64 for hashing (quick hash reads head/tail, full hash reads entire file).
- Deduplicate hardlinks (same inode/device) by only reporting one representative per inode.
- Choose which duplicate to keep via --keep {first,oldest,newest} (default oldest).
- Support --dry-run to only list what would be deleted.
- Use loguru for all logging output.
- Use pathlib exclusively for path operations.
- Include full type annotations and docstrings on all functions and module-level constants.
- Delete duplicates via Path.unlink() and print(a summary including bytes freed.)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path

from loguru import logger
from xxhash import xxh64

DEFAULT_BLOCK: int = 32768
QUICK_READ: int = 4096
CHUNK_SIZE: int = 65536
POOL_WORKERS: int = 8


def file_stat_key(p: Path) -> tuple[int, int] | None:
    """Return (st_ino, st_dev) for a path, or None on OSError."""
    try:
        st = p.stat()
        return (st.st_ino, st.st_dev)
    except OSError:
        return None


def quick_hash(path: Path, n: int = QUICK_READ) -> str:
    """Compute a fast hash from the head and tail of a file.

    Reads up to `n` bytes from the start and, if the file is large enough,
    up to `n` bytes from the end. For small files, reads the whole content.
    Raises OSError on I/O failures.
    """
    h = xxh64()
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(n)
            h.update(head)
            if size > n * 2:
                f.seek(max(size - n, 0))
                tail = f.read(n)
                h.update(tail)
            elif size > n:
                rest = f.read()
                h.update(rest)
    except OSError as e:
        raise OSError(f"quick_hash error {path}: {e}") from e
    return h.hexdigest()


def full_hash(path: Path) -> tuple[str, Path]:
    """Compute the full xxh64 hash of a file's contents.

    Returns ("", path) for empty files or on OSError.
    """
    try:
        if not path.stat().st_size:
            return ("", path)
    except OSError:
        return ("", path)
    h = xxh64()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return (h.hexdigest(), path)
    except OSError:
        return ("", path)


def iter_files(
    root: Path,
    recursive: bool,
    follow_symlinks: bool,
    min_size: int,
) -> Iterator[Path]:
    """Yield candidate files under `root` meeting the given filters.

    Skips anything inside a .git directory, non-files, and (by default)
    symlinks. Only yields files whose size is at least `min_size`.
    """
    if recursive:
        iterator: Iterable[Path] = root.rglob("*")
    else:
        iterator = root.iterdir()
    for p in iterator:
        if ".git" in p.parts:
            continue
        if not p.is_file():
            continue
        if p.is_symlink() and not follow_symlinks:
            continue
        try:
            if p.stat().st_size >= min_size:
                yield p
        except OSError:
            continue


def choose_keep(files: list[Path], policy: str = "oldest") -> Path:
    """Choose which file to keep from a list of duplicates.

    Policy may be "first" (lexicographic), "oldest" (mtime), or "newest" (mtime).
    """
    if not files:
        raise ValueError("Empty file list")
    if policy == "first":
        return min(files, key=str)
    elif policy == "oldest":
        return min(files, key=lambda p: p.stat().st_mtime)
    elif policy == "newest":
        return max(files, key=lambda p: p.stat().st_mtime)
    else:
        return min(files, key=str)


def main() -> None:
    """Entry point: scan, hash, and delete duplicate files."""
    cwd = Path.cwd()
    p = argparse.ArgumentParser(
        description="Find and delete duplicate files by content."
    )
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Search directories recursively (default: True).",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Don't delete; just show what would be done.",
    )
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        default=False,
        help="Follow symlinks to files.",
    )
    p.add_argument(
        "--min-size",
        type=int,
        default=1,
        help="Minimum file size (bytes) to consider. Default 1 (skip zero-size).",
    )
    p.add_argument(
        "-k",
        "--keep",
        choices=("first", "oldest", "newest"),
        default="oldest",
        help="Which file to keep within duplicates.",
    )
    args = p.parse_args()

    root = Path.cwd()

    print("Phase 1: Scanning files and grouping by size...")
    size_groups: defaultdict[int, list[Path]] = defaultdict(list)
    total_files = 0
    for f in iter_files(root, args.recursive, args.follow_symlinks, args.min_size):
        total_files += 1
        try:
            size = f.stat().st_size
            size_groups[size].append(f)
        except OSError:
            continue

    candidates: dict[int, list[Path]] = {
        s: lst for s, lst in size_groups.items() if len(lst) > 1
    }
    if not candidates:
        print(f"Scanned {total_files} files. No potential duplicates found.")
        return

    candidate_count = sum(len(v) for v in candidates.values())
    print(
        f"Phase 1 complete: {candidate_count} files in "
        f"{len(candidates)} size-groups to examine."
    )

    print("Phase 2: Quick hash comparison...")
    quick_groups: defaultdict[tuple[int, str], list[Path]] = defaultdict(list)

    with Pool(processes=POOL_WORKERS) as pool:
        futures: list[tuple[Path, object]] = []
        for files in candidates.values():
            for fpath in files:
                futures.append((fpath, pool.apply_async(quick_hash, (fpath,))))
        for fpath, fut in futures:
            try:
                h: str = fut.get()
                key = (fpath.stat().st_size, h)
                quick_groups[key].append(fpath)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skipping {fpath}: {e}")

    need_full: list[list[Path]] = [
        group for group in quick_groups.values() if len(group) > 1
    ]
    if not need_full:
        print("No duplicates found after quick hash comparison.")
        return

    full_candidates = sum(len(g) for g in need_full)
    print(
        f"Phase 2 complete: {full_candidates} files in "
        f"{len(need_full)} groups need full hash."
    )

    print("Phase 3: Full hash comparison...")
    full_groups: defaultdict[str, list[tuple[Path, tuple[int, int] | None]]] = (
        defaultdict(list)
    )

    with Pool(processes=POOL_WORKERS) as pool:
        futures2: list[tuple[Path, tuple[int, int] | None, object]] = []
        for group in need_full:
            for fpath in group:
                st_key = file_stat_key(fpath)
                futures2.append((fpath, st_key, pool.apply_async(full_hash, (fpath,))))
        for fpath, st_key, fut in futures2:
            try:
                h, _ = fut.get()
                if h:
                    full_groups[h].append((fpath, st_key))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skipping {fpath}: {e}")

    print("Phase 4: Processing results...")
    to_delete: list[Path] = []
    for entries in full_groups.values():
        if len(entries) < 2:
            continue
        inode_map: defaultdict[tuple[int, int] | None, list[Path]] = defaultdict(list)
        for p_path, stk in entries:
            inode_map[stk].append(p_path)
        group_reps: list[Path] = [min(ps, key=str) for ps in inode_map.values()]
        if len(group_reps) < 2:
            continue
        keep_file = choose_keep(group_reps, policy=args.keep)
        for rep in group_reps:
            if rep != keep_file:
                to_delete.append(rep)

    if not to_delete:
        print("No duplicate files found.")
        return

    print(f"\nFound {len(to_delete)} duplicate files to delete.")
    if args.dry_run:
        print("DRY RUN - Files that would be deleted:")
    else:
        print("Files to be deleted:")
    for p_del in to_delete:
        try:
            rel_path = p_del.relative_to(cwd)
        except ValueError:
            rel_path = p_del
        print(f"  {rel_path}")

    if args.dry_run:
        print(f"\nDry-run complete. {len(to_delete)} files would be deleted.")
        return

    removed = 0
    failed = 0
    freed_space = 0
    for p_del in to_delete:
        try:
            size = p_del.stat().st_size
            p_del.unlink()
            freed_space += size
            removed += 1
            try:
                print(f"Deleted: {p_del.relative_to(cwd)} ({size:,} bytes)")
            except ValueError:
                print(f"Deleted: {p_del} ({size:,} bytes)")
        except OSError as e:
            failed += 1
            try:
                logger.error(f"Failed: {p_del.relative_to(cwd)} - {e}")
            except ValueError:
                logger.error(f"Failed: {p_del} - {e}")

    print("\nSummary:")
    print(f"  Files scanned: {total_files}")
    print(f"  Duplicates found: {len(to_delete)}")
    print(f"  Successfully deleted: {removed}")
    if failed:
        print(f"  Failed to delete: {failed}")
    if freed_space:
        print(
            f"  Space freed: {freed_space:,} bytes ({freed_space / 1024 / 1024:.2f} MB)"
        )


if __name__ == "__main__":
    raise SystemExit(main())
