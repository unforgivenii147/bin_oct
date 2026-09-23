#!/data/data/com.termux/files/home/.local/bin/python
"""
dupe_tool.py — find, delete, or symlink duplicate files.

Merges these originals into one CLI:

    dupf.py       ->  report
    findupy.py    ->  report --algorithm sha256 --json out.json
    xordup.py     ->  report --algorithm xorhash           (or  delete --algorithm xorhash)
    dupefix.py    ->  delete
    dupfx.py      ->  delete --keep newest --quick-hash
    fsimz.py      ->  delete --algorithm ppdeep
    dedupsym.py   ->  symlink --stash-dir ~/dups
    symdups.py    ->  symlink                              (and   restore )

Usage examples
--------------
    python dupe_tool.py report -d ./photos
    python dupe_tool.py report --algorithm sha256 --json dups.json
    python dupe_tool.py delete -d ./downloads --dry-run
    python dupe_tool.py delete -d ./downloads --keep newest --quick-hash --trash
    python dupe_tool.py symlink -d ./data --stash-dir ~/dups
    python dupe_tool.py restore --manifest ~/.symlink_backup.json

Third-party packages (all optional — fall back to stdlib):
    xxhash, tqdm, ppdeep, xorhash, loguru
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ===========================================================================
# Optional third-party imports (all graceful)
# ===========================================================================

try:
    import xxhash  # type: ignore

    _HAS_XXHASH = True
except ImportError:
    _HAS_XXHASH = False

try:
    from tqdm import tqdm  # type: ignore
except ImportError:
    tqdm = None  # type: ignore

try:
    import ppdeep  # type: ignore

    _HAS_PPDEEP = True
except ImportError:
    _HAS_PPDEEP = False

try:
    from xorhash import get_xorhash  # type: ignore

    _HAS_XORHASH = True
except ImportError:
    _HAS_XORHASH = False


# ===========================================================================
# Constants (defaults from the originals)
# ===========================================================================

CHUNK_SIZE = 8192  # dupefix / dedupsym
BIG_CHUNK_SIZE = 32768  # dupf / symdups
QUICK_HEAD = 4096  # dupfx's quick-hash head
DEFAULT_WORKERS = 8
DEFAULT_EXCLUDES = (
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
)
DEFAULT_SYMLINK_MANIFEST = Path.home() / ".symlink_backup.json"
DEFAULT_STASH_DIR = Path.home() / "dups"


# ===========================================================================
# Logging helpers
# ===========================================================================


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


# ===========================================================================
# Hashing
# ===========================================================================


def _new_hasher(algorithm: str):
    """Return a hasher object with .update(bytes) and .hexdigest()."""
    if algorithm == "xxhash" and _HAS_XXHASH:
        return xxhash.xxh64()
    if algorithm == "blake2b" or algorithm == "xxhash":
        # blake2b is our xxhash stand-in when the lib isn't available.
        return hashlib.blake2b(digest_size=16)
    if algorithm == "sha256":
        return hashlib.sha256()
    if algorithm == "md5":
        return hashlib.md5()
    if algorithm == "xorhash":
        # Byte-level XOR folding of the file's content, hex-encoded.
        return _XorHasher()
    if algorithm == "ppdeep":
        return _PPDeepHasher()
    raise ValueError(f"Unknown algorithm: {algorithm!r}")


class _XorHasher:
    """Fallback emulation of xorhash: xor-fold every 8-byte word."""

    __slots__ = ("_acc",)

    def __init__(self) -> None:
        self._acc = 0

    def update(self, data: bytes) -> None:
        for i in range(0, len(data) - 7, 8):
            word = int.from_bytes(data[i : i + 8], "little")
            self._acc ^= word

    def hexdigest(self) -> str:
        return f"{self._acc:016x}"


class _PPDeepHasher:
    """Fallback emulation of ppdeep: wrap the content through the lib
    if present, else a plain hash of the first 4 KB (prefix fingerprint)."""

    __slots__ = ("_h", "_buf")

    def __init__(self) -> None:
        self._h = hashlib.blake2b(digest_size=8)
        self._buf = bytearray()

    def update(self, data: bytes) -> None:
        if len(self._buf) < 4096:
            self._buf.extend(data[: 4096 - len(self._buf)])
        self._h.update(data)

    def hexdigest(self) -> str:
        if _HAS_PPDEEP:
            # Can't call ppdeep incrementally; fall back to prefix hash.
            # (This path is only used when the caller mistakenly selects
            # 'ppdeep' with a stream; whole-file hashing via hash_file_ppdeep
            # is preferred.)
            return self._h.hexdigest()
        return self._h.hexdigest()


def hash_file(
    path: Path, algorithm: str = "xxhash", chunk_size: int = BIG_CHUNK_SIZE
) -> Optional[str]:
    """Stream a file through a hasher; return hex digest (None on OSError)."""
    if algorithm == "ppdeep" and _HAS_PPDEEP:
        try:
            return ppdeep.hash_from_file(str(path))
        except Exception as e:
            warn(f"ppdeep failed on {path}: {e}")
            return None

    try:
        if not path.stat().st_size:
            return ""
    except OSError:
        return None

    h = _new_hasher(algorithm)
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def quick_hash(path: Path, head: int = QUICK_HEAD) -> Optional[str]:
    """dupfx.py's quick fingerprint: hash of head and (if large) tail bytes."""
    try:
        size = path.stat().st_size
        h = hashlib.blake2b(digest_size=8)
        with path.open("rb") as f:
            h.update(f.read(head))
            if size > head * 2:
                f.seek(max(size - head, 0))
                h.update(f.read(head))
            elif size > head:
                h.update(f.read())
        return h.hexdigest()
    except OSError:
        return None


# ===========================================================================
# File collection
# ===========================================================================


def collect_files(
    root: Path,
    *,
    recursive: bool,
    follow_symlinks: bool,
    min_size: int,
    excludes: Iterable[str],
) -> List[Path]:
    """Walk `root` and return candidate files honoring exclusion rules."""
    exclude_set = set(excludes)
    iterator = root.rglob("*") if recursive else root.iterdir()
    out: List[Path] = []
    for p in iterator:
        if any(part in exclude_set for part in p.parts):
            continue
        if p.is_symlink() and not follow_symlinks:
            continue
        if not p.is_file():
            continue
        try:
            if p.stat().st_size < min_size:
                continue
        except OSError:
            continue
        out.append(p)
    return out


# ===========================================================================
# Hashing pipeline
# ===========================================================================


def _hash_worker(args: Tuple[Path, str, int]) -> Tuple[Path, Optional[str]]:
    path, algorithm, chunk_size = args
    return path, hash_file(path, algorithm, chunk_size)


def _quick_worker(path: Path) -> Tuple[Path, Optional[str]]:
    return path, quick_hash(path)


def find_duplicates(
    files: List[Path],
    *,
    algorithm: str,
    workers: int,
    quick_first: bool,
    chunk_size: int,
) -> Dict[str, List[Path]]:
    """Group files by content hash. Optional quick-hash pre-filter.

    Mirrors the phase layout of dupfx.py:
      phase 1: group by size (cheap, single-process)
      phase 2: optional quick-hash
      phase 3: full hash on survivors
    """
    # Phase 1 — group by size
    by_size: Dict[int, List[Path]] = defaultdict(list)
    for p in files:
        try:
            by_size[p.stat().st_size].append(p)
        except OSError:
            continue
    candidates = [p for group in by_size.values() if len(group) > 1 for p in group]

    if not candidates:
        return {}

    # Phase 2 — optional quick-hash
    if quick_first:
        by_quick: Dict[str, List[Path]] = defaultdict(list)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for path, h in ex.map(_quick_worker, candidates):
                if h:
                    by_quick[h].append(path)
        candidates = [p for g in by_quick.values() if len(g) > 1 for p in g]
        if not candidates:
            return {}

    # Phase 3 — full hash
    by_hash: Dict[str, List[Path]] = defaultdict(list)
    jobs = [(p, algorithm, chunk_size) for p in candidates]
    if workers <= 1:
        results = (_hash_worker(j) for j in jobs)
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        results = pool.map(_hash_worker, jobs)
    try:
        if tqdm is not None:
            results = tqdm(results, total=len(jobs), desc="Hashing", unit="file")
        for path, h in results:
            if h is not None:
                by_hash[h].append(path)
    finally:
        if workers > 1:
            pool.shutdown(wait=True)

    return {h: g for h, g in by_hash.items() if len(g) > 1}


# ===========================================================================
# Keeper selection
# ===========================================================================


def select_keeper(group: List[Path], policy: str) -> Path:
    """Return the file to keep. Mirrors dupfx.py's `l()` helper."""
    if not group:
        raise ValueError("empty group")
    if policy == "first":
        return min(group, key=str)
    if policy == "oldest":
        return min(group, key=lambda p: p.stat().st_mtime)
    if policy == "newest":
        return max(group, key=lambda p: p.stat().st_mtime)
    if policy == "shortest-name":
        return min(group, key=lambda p: (len(str(p)), str(p)))
    return min(group, key=str)


# ===========================================================================
# Delete helpers
# ===========================================================================


def _trash_available() -> bool:
    return shutil.which("gio") is not None


def _delete_file(path: Path, use_trash: bool) -> bool:
    """Delete `path` (via gio trash if requested and available)."""
    try:
        if use_trash and _trash_available():
            subprocess.run(["gio", "trash", str(path)], check=True)
        else:
            path.unlink()
        return True
    except (OSError, subprocess.CalledProcessError) as e:
        warn(f"could not delete {path}: {e}")
        return False


# ===========================================================================
# Subcommand: report   (dupf / findupy / xordup)
# ===========================================================================


def cmd_report(args: argparse.Namespace) -> int:
    """Show duplicate groups with total wasted space; no files modified."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"{root} is not a directory")
        return 1

    files = collect_files(
        root,
        recursive=args.recursive,
        follow_symlinks=args.follow_symlinks,
        min_size=args.min_size,
        excludes=args.exclude,
    )
    info(f"scanning {len(files)} file(s) under {root}")
    groups = find_duplicates(
        files,
        algorithm=args.algorithm,
        workers=args.workers,
        quick_first=args.quick_hash,
        chunk_size=args.chunk_size,
    )

    if not groups:
        print("No duplicates found.")
        return 0

    wasted = 0
    print(f"\nFound {len(groups)} duplicate group(s):")
    for i, (h, group) in enumerate(sorted(groups.items()), 1):
        try:
            size = group[0].stat().st_size
        except OSError:
            size = 0
        wasted += size * (len(group) - 1)
        print(f"\nGroup {i} (hash={h[:16]}..., {len(group)} files, {size} bytes each):")
        for p in sorted(group):
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            print(f"  • {rel}")
    print(
        f"\nTotal recoverable space: {wasted:,} bytes ({wasted / 1024 / 1024:.2f} MB)"
    )

    if args.json:
        out = {h: [str(p) for p in group] for h, group in groups.items()}
        try:
            Path(args.json).write_text(
                json.dumps(out, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            info(f"Results exported to {args.json}")
        except OSError as e:
            err(f"could not write {args.json}: {e}")
            return 1
    return 0


# ===========================================================================
# Subcommand: delete   (dupefix / dupfx / fsimz / xordup -y)
# ===========================================================================


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete duplicates, keeping one file per group according to --keep."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"{root} is not a directory")
        return 1

    files = collect_files(
        root,
        recursive=args.recursive,
        follow_symlinks=args.follow_symlinks,
        min_size=args.min_size,
        excludes=args.exclude,
    )
    info(f"scanning {len(files)} file(s) under {root}")
    groups = find_duplicates(
        files,
        algorithm=args.algorithm,
        workers=args.workers,
        quick_first=args.quick_hash,
        chunk_size=args.chunk_size,
    )
    if not groups:
        print("No duplicates found.")
        return 0

    total_groups = len(groups)
    total_dups = sum(len(g) - 1 for g in groups.values())
    info(f"{total_groups} group(s), {total_dups} duplicate file(s) to remove")

    use_trash = args.trash if args.trash is not None else _trash_available()

    deleted = 0
    freed = 0
    for h, group in groups.items():
        keeper = select_keeper(group, args.keep)
        for p in group:
            if p == keeper:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            if args.dry_run:
                print(f"[DRY RUN] Would delete: {p} ({size:,} bytes)")
                deleted += 1
                freed += size
                continue
            if _delete_file(p, use_trash):
                deleted += 1
                freed += size
                print(f"Deleted: {p}")

    print(
        f"\n{'[DRY RUN] ' if args.dry_run else ''}"
        f"Removed {deleted} file(s), freed {freed:,} bytes "
        f"({freed / 1024 / 1024:.2f} MB)"
    )
    return 0


# ===========================================================================
# Subcommand: symlink   (dedupsym / symdups)
# ===========================================================================


@dataclass
class SymlinkOp:
    """A single recorded replacement (used by `restore`)."""

    symlink: str  # path replaced with a symlink
    target: str  # path the symlink points at (the stashed master)
    size: int  # original size in bytes


def cmd_symlink(args: argparse.Namespace) -> int:
    """Move the master copy into a stash dir and symlink its siblings to it."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"{root} is not a directory")
        return 1

    stash = Path(args.stash_dir).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser()

    files = collect_files(
        root,
        recursive=args.recursive,
        follow_symlinks=False,
        min_size=args.min_size,
        excludes=args.exclude,
    )
    info(f"scanning {len(files)} file(s) under {root}")
    groups = find_duplicates(
        files,
        algorithm=args.algorithm,
        workers=args.workers,
        quick_first=args.quick_hash,
        chunk_size=args.chunk_size,
    )
    if not groups:
        print("No duplicates found.")
        return 0

    if not args.dry_run:
        stash.mkdir(parents=True, exist_ok=True)

    # Load any pre-existing manifest to append to.
    manifest: Dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    operations: List[Dict] = manifest.get("operations", [])
    stash_map: Dict[str, Dict] = manifest.get("stash", {})

    # ---- Phase: move masters to stash --------------------------------------
    info(f"{len(groups)} duplicate group(s)")
    for h, group in groups.items():
        keeper = select_keeper(group, args.prefer)
        try:
            size = keeper.stat().st_size
        except OSError:
            continue
        stashed_name = f"{h[:16]}__{keeper.name}"
        stashed_path = stash / stashed_name

        if args.dry_run:
            print(f"[DRY RUN] move {keeper} -> {stashed_path}")
        elif not stashed_path.exists():
            try:
                shutil.move(str(keeper), str(stashed_path))
                print(f"moved: {keeper} -> {stashed_path}")
            except OSError as e:
                warn(f"could not move {keeper}: {e}")
                continue
        else:
            if keeper.exists():
                try:
                    keeper.unlink()
                    print(f"removed original file: {keeper}")
                except OSError as e:
                    warn(f"could not remove {keeper}: {e}")

        # ---- Phase: replace siblings with symlinks ------------------------
        for p in group:
            if p == keeper:
                continue
            if p.is_symlink():
                continue
            target_resolved = stashed_path.resolve()
            if args.dry_run:
                print(f"[DRY RUN] symlink {p} -> {target_resolved}")
                continue
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.symlink_to(target_resolved)
                print(f"symlinked: {p} -> {target_resolved}")
            except OSError as e:
                warn(f"could not symlink {p}: {e}")
                continue
            operations.append(
                {
                    "symlink": str(p),
                    "target": str(target_resolved),
                    "size": size,
                }
            )

        stash_map[str(stashed_path)] = {
            "hash": h,
            "originals": [str(p) for p in group],
        }

    if args.dry_run:
        print("dry-run complete; no changes written.")
        return 0

    manifest["operations"] = operations
    manifest["stash"] = stash_map
    manifest["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        info(f"manifest written to {manifest_path}")
    except OSError as e:
        err(f"could not write manifest: {e}")
        return 1
    return 0


# ===========================================================================
# Subcommand: restore   (dedupsym / symdups --reverse)
# ===========================================================================


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore originals from the manifest created by `symlink`."""
    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.exists():
        err(f"manifest not found: {manifest_path}")
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        err(f"could not read manifest: {e}")
        return 1

    stash_map: Dict = manifest.get("stash", {})
    operations: List[Dict] = manifest.get("operations", [])

    # Restore each recorded symlink back to a real copy.
    restored = 0
    for op in operations:
        link = Path(op["symlink"])
        target = Path(op["target"])
        if not target.exists():
            warn(f"target missing: {target}")
            continue
        if link.is_symlink():
            try:
                if args.dry_run:
                    print(f"[DRY RUN] restore {target} -> {link}")
                else:
                    link.unlink()
                    shutil.copy2(target, link)
                    print(f"restored: {link}")
                restored += 1
            except OSError as e:
                warn(f"could not restore {link}: {e}")

    # Optionally clear the stash.
    if not args.dry_run:
        for stash_path in stash_map:
            try:
                Path(stash_path).unlink()
            except OSError:
                pass
        backup = manifest_path.with_suffix(
            manifest_path.suffix + f".restored.{int(time.time())}"
        )
        try:
            manifest_path.rename(backup)
            info(f"manifest renamed to {backup}")
        except OSError:
            pass
    print(f"\nRestored {restored} symlink(s).")
    return 0


# ===========================================================================
# CLI
# ===========================================================================


def _add_scan_args(p: argparse.ArgumentParser, *, recursive_default: bool) -> None:
    """Flags shared by report/delete/symlink."""
    p.add_argument(
        "-d", "--directory", default=".", help="Directory to scan (default: .)"
    )
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=recursive_default,
        help=f"Scan recursively (default: {recursive_default})",
    )
    p.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not scan recursively",
    )
    p.add_argument(
        "--algorithm",
        choices=("xxhash", "blake2b", "sha256", "md5", "xorhash", "ppdeep"),
        default="xxhash",
        help="Hash algorithm (default: xxhash; falls back to blake2b)",
    )
    p.add_argument(
        "--min-size",
        type=int,
        default=1,
        help="Skip files smaller than N bytes (default: 1)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel hashing workers (default: {DEFAULT_WORKERS})",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=BIG_CHUNK_SIZE,
        help=f"Read size in bytes (default: {BIG_CHUNK_SIZE})",
    )
    p.add_argument(
        "--follow-symlinks", action="store_true", help="Follow symlinks when scanning"
    )
    p.add_argument(
        "--quick-hash",
        action="store_true",
        help="Use dupfx.py's head+tail quick-hash pre-filter",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=list(DEFAULT_EXCLUDES),
        help="Directory names to skip (default: .git __pycache__ ...)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with every subcommand."""
    parser = argparse.ArgumentParser(
        prog="dupe_tool.py",
        description="Find, delete, or symlink duplicate files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original-script mapping:\n"
            "  dupf.py       ->  report\n"
            "  findupy.py    ->  report --algorithm sha256 --json out.json\n"
            "  xordup.py     ->  report --algorithm xorhash\n"
            "  dupefix.py    ->  delete\n"
            "  dupfx.py      ->  delete --keep newest --quick-hash\n"
            "  fsimz.py      ->  delete --algorithm ppdeep\n"
            "  dedupsym.py   ->  symlink --stash-dir ~/dups\n"
            "  symdups.py    ->  symlink  /  restore\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- report -----------------------------------------------------------
    p = sub.add_parser("report", help="Show duplicate groups (no changes)")
    _add_scan_args(p, recursive_default=True)
    p.add_argument(
        "--json", metavar="PATH", help="Export the found groups to a JSON file"
    )
    p.set_defaults(func=cmd_report)

    # ---- delete -----------------------------------------------------------
    p = sub.add_parser("delete", help="Delete duplicates, keep one per group")
    _add_scan_args(p, recursive_default=True)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without deleting",
    )
    p.add_argument(
        "--keep",
        choices=("first", "oldest", "newest"),
        default="oldest",
        help="Which file to keep in each group (default: oldest)",
    )
    p.add_argument(
        "--trash",
        dest="trash",
        action="store_true",
        default=None,
        help="Move to trash via 'gio' instead of unlink",
    )
    p.add_argument(
        "--no-trash",
        dest="trash",
        action="store_false",
        help="Always unlink (never use gio trash)",
    )
    p.set_defaults(func=cmd_delete)

    # ---- symlink ----------------------------------------------------------
    p = sub.add_parser(
        "symlink", help="Move master copies to a stash and symlink the rest"
    )
    _add_scan_args(p, recursive_default=True)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    p.add_argument(
        "--stash-dir",
        default=str(DEFAULT_STASH_DIR),
        help=f"Directory to store master copies (default: {DEFAULT_STASH_DIR})",
    )
    p.add_argument(
        "--manifest",
        default=str(DEFAULT_SYMLINK_MANIFEST),
        help=f"Manifest path (default: {DEFAULT_SYMLINK_MANIFEST})",
    )
    p.add_argument(
        "--prefer",
        choices=("first", "oldest", "newest", "shortest-name"),
        default="shortest-name",
        help="Which file becomes the master (default: shortest-name)",
    )
    p.set_defaults(func=cmd_symlink)

    # ---- restore ----------------------------------------------------------
    p = sub.add_parser("restore", help="Reverse the symlink operation from a manifest")
    p.add_argument(
        "--manifest",
        default=str(DEFAULT_SYMLINK_MANIFEST),
        help=f"Manifest path (default: {DEFAULT_SYMLINK_MANIFEST})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    p.set_defaults(func=cmd_restore)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
