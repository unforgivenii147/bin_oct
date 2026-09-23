#!/data/data/com.termux/files/home/.local/bin/python
"""
img_similarity.py — unified image similarity / deduplication toolkit.

Merges the following original scripts into one CLI:

    dupimg.py                             ->  scan --method dct-phash --threshold 4
    find_sim_images.py <algo> <dir>       ->  scan --method <algo> --threshold 0
    folderim.py                           ->  organize --method phash --threshold 10
    folderimg.py                          ->  organize --method multihash --threshold 10
    folderize_images.py                   ->  organize --method phash --hash-size 16 --out _similar_groups
    folderize_images_by_similarity.py     ->  organize --method ahash --mode similarity --threshold 0.95
    imgdedup.py <dir> [--remove]          ->  dedup --method dhash-custom [--no-dry-run]
    keeponeingroups.py                    ->  keep-one --yes
    organize_images.py                    ->  cluster -k 10 --threshold 0.7

Third-party packages (as used by the originals):
    Pillow, imagehash    -- imagehash-based methods
    opencv-python (cv2)  -- dct-phash, dhash-custom, hist features
    numpy                -- array operations

Only the packages needed by the chosen --method are imported.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".heic",
    ".heif",
    ".raw",
    ".svg",
}

# Default Hamming thresholds per method (mirrors each original's hardcoded value).
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "dct-phash": 4,  # dupimg.py DUP_HASH_THRESHOLD default
    "dhash-custom": 4,  # imgdedup.py (exact-hash grouping)
    "ahash": 8,  # imagehash defaults / folderize_images.py
    "phash": 8,
    "dhash": 8,
    "whash-haar": 8,
    "whash-db4": 8,
    "colorhash": 8,
    "crop-resistant": 8,
    "multihash": 10.0,  # folderimg.py
}

METHODS = tuple(DEFAULT_THRESHOLDS.keys())

# folderimg.py weights for the composite "multihash" distance.
MULTIHASH_W = {"phash": 0.5, "dhash": 0.3, "ahash": 0.2}

# The imagehash-based methods share a single dispatcher.
_IMAGEHASH_METHODS = {
    "ahash",
    "phash",
    "dhash",
    "whash-haar",
    "whash-db4",
    "colorhash",
    "crop-resistant",
}


# ---------------------------------------------------------------------------
# Logging helpers (uniform across subcommands)
# ---------------------------------------------------------------------------


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def _require(modname: str, method: str) -> bool:
    """Return True if `modname` is importable, else print a clear error."""
    try:
        __import__(modname)
        return True
    except ImportError:
        err(
            f"Package {modname!r} is required for method {method!r}. "
            f"Install with: pip install {modname}"
        )
        return False


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def hash_dct_phash(path: Path, hash_size: int = 16) -> Optional[str]:
    """dupimg.py: resize → grayscale → DCT → top-left 8x8 vs mean → bit-string."""
    if not _require("cv2", "dct-phash"):
        return None
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    try:
        img = cv2.imread(str(path))
        if img is None:
            return None
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(img, (hash_size, hash_size), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
        dct = cv2.dct(np.float32(gray))
        top = dct[:8, :8]
        mean = np.mean(top)
        bits = (top > mean).flatten()
        return "".join(bits.astype(int).astype(str))
    except Exception as e:
        warn(f"dct-phash failed on {path.name}: {e}")
        return None


def hash_dhash_custom(path: Path, hash_size: int = 8) -> Optional[int]:
    """imgdedup.py: dHash as an integer bitmask (uses cv2)."""
    if not _require("cv2", "dhash-custom"):
        return None
    import cv2  # type: ignore

    try:
        img = cv2.imread(str(path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (hash_size + 1, hash_size))
        diff = resized[:, 1:] > resized[:, :-1]
        return sum(2**i for i, v in enumerate(diff.flatten()) if v)
    except Exception as e:
        warn(f"dhash-custom failed on {path.name}: {e}")
        return None


def hash_imagehash(path: Path, method: str, hash_size: int = 8):
    """imagehash-based hashes; supports the 7 algorithms the originals used."""
    if not (_require("PIL", method) and _require("imagehash", method)):
        return None
    from PIL import Image  # type: ignore
    import imagehash  # type: ignore

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if method == "ahash":
                return imagehash.average_hash(im, hash_size=hash_size)
            if method == "phash":
                return imagehash.phash(im, hash_size=hash_size)
            if method == "dhash":
                return imagehash.dhash(im, hash_size=hash_size)
            if method == "whash-haar":
                return imagehash.whash(im, hash_size=hash_size)
            if method == "whash-db4":
                return imagehash.whash(im, hash_size=hash_size, mode="db4")
            if method == "colorhash":
                # imagehash.colorhash has a different signature; skip hash_size.
                return imagehash.colorhash(im)
            if method == "crop-resistant":
                return imagehash.crop_resistant_hash(im)
    except Exception as e:
        warn(f"{method} failed on {path.name}: {e}")
        return None


def hash_multihash(path: Path, hash_size: int = 8) -> Optional[Dict[str, Any]]:
    """folderimg.py: dict of phash/dhash/ahash for weighted comparison."""
    if not (_require("PIL", "multihash") and _require("imagehash", "multihash")):
        return None
    from PIL import Image  # type: ignore
    import imagehash  # type: ignore

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            return {
                "phash": imagehash.phash(im, hash_size=hash_size),
                "dhash": imagehash.dhash(im, hash_size=hash_size),
                "ahash": imagehash.average_hash(im, hash_size=hash_size),
            }
    except Exception as e:
        warn(f"multihash failed on {path.name}: {e}")
        return None


def feature_hist(path: Path, size: Tuple[int, int] = (64, 64)) -> Optional[Any]:
    """organize_images.py: HSV histogram (8 bins × 3 channels) + raw pixels."""
    if not (_require("cv2", "hist") and _require("numpy", "hist")):
        return None
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    try:
        img = cv2.imread(str(path))
        if img is None or img.size == 0:
            return None
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        resized = cv2.resize(img, size)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0], None, [8], [0, 180])
        s = cv2.calcHist([hsv], [1], None, [8], [0, 256])
        v = cv2.calcHist([hsv], [2], None, [8], [0, 256])
        flat = resized.flatten()
        vec = np.concatenate([h.flatten(), s.flatten(), v.flatten(), flat])
        n = np.linalg.norm(vec)
        if n > 0:
            vec = vec / n
        return vec
    except Exception as e:
        warn(f"hist failed on {path.name}: {e}")
        return None


def extract_feature(path: Path, method: str, hash_size: int) -> Optional[Any]:
    """Dispatch to the right feature extractor for the chosen method."""
    if method == "dct-phash":
        return hash_dct_phash(path, hash_size)
    if method == "dhash-custom":
        return hash_dhash_custom(path, hash_size)
    if method in _IMAGEHASH_METHODS:
        return hash_imagehash(path, method, hash_size)
    if method == "multihash":
        return hash_multihash(path, hash_size)
    raise ValueError(f"Unknown method: {method!r}")


# ---------------------------------------------------------------------------
# Distance functions
# ---------------------------------------------------------------------------


def hamming_str(a: Any, b: Any) -> int:
    """Hamming distance between two equal-length bit-strings."""
    if a is None or b is None:
        return 10**9
    return sum(x != y for x, y in zip(a, b))


def hamming_int(a: Any, b: Any) -> int:
    """Hamming distance between two integer bitmasks."""
    if a is None or b is None:
        return 10**9
    return bin(int(a) ^ int(b)).count("1")


def multihash_dist(a: Any, b: Any) -> float:
    """folderimg.py's weighted distance over phash/dhash/ahash."""
    if a is None or b is None:
        return float("inf")
    d = 0.0
    for key, weight in MULTIHASH_W.items():
        d += abs(a[key] - b[key]) * weight
    return d


def distance(method: str, a: Any, b: Any) -> float:
    """Return the distance between two features (lower = more similar)."""
    if a is None or b is None:
        return float("inf")
    if method == "dct-phash":
        return hamming_str(a, b)
    if method == "dhash-custom":
        return hamming_int(a, b)
    if method == "multihash":
        return multihash_dist(a, b)
    try:
        return int(a - b)  # imagehash objects support subtraction → Hamming
    except Exception:
        return float("inf")


def max_hamming_distance(method: str, hash_size: int) -> Optional[int]:
    """Return the maximum Hamming distance for a method (used in similarity mode)."""
    if method == "dct-phash":
        return 64
    if method == "dhash-custom":
        return hash_size * hash_size
    if method == "multihash":
        return hash_size * hash_size
    if method in ("ahash", "phash", "dhash", "whash-haar", "whash-db4"):
        return hash_size * hash_size
    if method == "colorhash":
        return 42  # imagehash's colorhash uses 14*3 bits
    return None  # crop-resistant has variable length


# ---------------------------------------------------------------------------
# Image collection & feature computation
# ---------------------------------------------------------------------------


def collect_images(
    root: Path, recursive: bool, exclude_parts: Iterable[str]
) -> List[Path]:
    """Return files under `root` whose suffix is supported, excluding dirs."""
    ex_set = {p for p in exclude_parts if p}
    iterator = root.rglob("*") if recursive else root.glob("*")
    out: List[Path] = []
    for p in iterator:
        if not p.is_file():
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        if ex_set and any(part in ex_set for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def compute_features(
    paths: Sequence[Path], method: str, hash_size: int, workers: int
) -> List[Tuple[Path, Any]]:
    """Compute features for all paths; returns [(path, feature), ...]."""
    items: List[Tuple[Path, Any]] = []
    if workers <= 1 or len(paths) <= 1:
        for p in paths:
            f = extract_feature(p, method, hash_size)
            if f is not None:
                items.append((p, f))
        return items
    # ThreadPool: mirrors dupimg.py; cv2 releases the GIL for its heavy ops.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [(p, ex.submit(extract_feature, p, method, hash_size)) for p in paths]
        for p, fut in futures:
            f = fut.result()
            if f is not None:
                items.append((p, f))
    return items


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def group_items(
    items: Sequence[Tuple[Path, Any]],
    method: str,
    threshold: float,
    similarity_mode: bool,
    hash_size: int,
) -> List[List[Path]]:
    """
    Greedy grouping: O(n²) pairwise comparison, matches every original's
    semantics. Returns a list of path groups (singletons included).
    """
    if similarity_mode:
        max_bits = max_hamming_distance(method, hash_size)
        if max_bits is None:
            raise ValueError(
                f"Similarity mode is not supported for method {method!r} "
                f"(hashes are variable-length)."
            )
        dist_threshold = (1.0 - float(threshold)) * max_bits
    else:
        dist_threshold = float(threshold)

    groups: List[List[Path]] = []
    assigned: set = set()
    n = len(items)
    for i in range(n):
        pi, fi = items[i]
        if pi in assigned:
            continue
        g: List[Path] = [pi]
        assigned.add(pi)
        for j in range(i + 1, n):
            pj, fj = items[j]
            if pj in assigned:
                continue
            if distance(method, fi, fj) <= dist_threshold:
                g.append(pj)
                assigned.add(pj)
        groups.append(g)
    return groups


# ---------------------------------------------------------------------------
# Helpers shared by pipeline subcommands
# ---------------------------------------------------------------------------


def file_size_mb(p: Path) -> float:
    try:
        return p.stat().st_size / 1048576
    except Exception:
        return 0.0


def resolve_threshold(args: argparse.Namespace) -> float:
    """Determine the effective threshold from CLI args + mode + method."""
    if args.threshold is not None:
        return float(args.threshold)
    if args.mode == "similarity":
        return 0.9
    return DEFAULT_THRESHOLDS.get(args.method, 8)


def resolve_hash_size(args: argparse.Namespace) -> int:
    """Default hash-size depends on the chosen method."""
    if args.hash_size is not None:
        return args.hash_size
    return 16 if args.method == "dct-phash" else 8


def _pipeline(args: argparse.Namespace):
    """
    Common front-end for scan / organize / dedup:
    scan directory → compute features → group → return (root, multi_groups, threshold).
    Returns None on unrecoverable issues (already printed).
    """
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"Not a directory: {root}")
        return None

    exclude = set()
    if getattr(args, "out", None):
        # Avoid re-scanning the output prefix from a previous run.
        exclude.add(str(args.out).split("/")[0])
    for e in getattr(args, "exclude", None) or []:
        exclude.add(e)

    hash_size = resolve_hash_size(args)
    paths = collect_images(root, args.recursive, exclude)
    info(f"Found {len(paths)} image(s) under {root}")
    if not paths:
        return None

    info(
        f"Computing features (method={args.method}, hash_size={hash_size}, "
        f"workers={args.workers})..."
    )
    t0 = time.time()
    items = compute_features(paths, args.method, hash_size, args.workers)
    info(f"Computed {len(items)} feature(s) in {time.time() - t0:.2f}s")
    if not items:
        warn("No readable images found.")
        return None

    threshold = resolve_threshold(args)
    try:
        groups = group_items(
            items, args.method, threshold, args.mode == "similarity", hash_size
        )
    except ValueError as e:
        err(str(e))
        return None

    multi = [g for g in groups if len(g) > 1]
    return root, multi, threshold


# ---------------------------------------------------------------------------
# Subcommand: scan
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> int:
    """Report groups of similar / duplicate images without touching any files."""
    res = _pipeline(args)
    if res is None:
        print("Nothing to do.")
        return 0
    root, multi, threshold = res
    if not multi:
        print("No duplicates (near-duplicates) found.")
        return 0

    print(f"\n{'=' * 44}")
    print(
        f"Found {len(multi)} similar group(s)  "
        f"(method={args.method}, threshold={threshold}, mode={args.mode})"
    )
    print(f"{'=' * 44}\n")

    for i, g in enumerate(sorted(multi, key=len, reverse=True), 1):
        print(f"Group #{i} ({len(g)} file(s)):")
        print("-" * 44)
        for p in sorted(g):
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            print(f"  • {rel}  ({file_size_mb(p):.2f} MB)")
        print()
    return 0


# ---------------------------------------------------------------------------
# Subcommand: organize
# ---------------------------------------------------------------------------


def cmd_organize(args: argparse.Namespace) -> int:
    """Move (or copy) grouped images into `<out_prefix>_NNN/` folders."""
    res = _pipeline(args)
    if res is None:
        print("Nothing to do.")
        return 0
    root, multi, _threshold = res
    if not multi:
        print("No duplicates (near-duplicates) found.")
        return 0

    out_prefix = args.out
    dry = args.dry_run
    action = args.action

    print(
        f"\nOrganizing {len(multi)} group(s) into {out_prefix}_NNN/  "
        f"(action={action}{', DRY RUN' if dry else ''})"
    )

    created = 0
    moved = 0
    for i, g in enumerate(sorted(multi, key=len, reverse=True), 1):
        folder = root / f"{out_prefix}_{i:03d}"
        if not dry:
            # parents=True handles `--out _similar_groups/group`.
            folder.mkdir(parents=True, exist_ok=True)
        info(f"{'[DRY RUN] ' if dry else ''}Folder: {folder.name}")
        created += 1
        for p in g:
            dst = folder / p.name
            # Avoid clobbering on filename collision (as in folderize_images.py).
            if dst.exists() and dst != p:
                stem, suffix = p.stem, p.suffix
                k = 1
                while dst.exists():
                    dst = folder / f"{stem}_{k}{suffix}"
                    k += 1
            if dry:
                info(f"  [DRY RUN] Would {action} {p.name} → {folder.name}/")
                moved += 1
                continue
            try:
                if action == "move":
                    shutil.move(str(p), str(dst))
                else:
                    shutil.copy2(str(p), str(dst))
                moved += 1
            except Exception as e:
                err(f"Failed to {action} {p}: {e}")

    print(f"\n{'=' * 44}")
    if dry:
        print(
            f"[DRY RUN] Would create {created} folder(s) and {action} {moved} file(s)."
        )
    else:
        print(f"✓ Created {created} folder(s) and {action}d {moved} file(s).")
    print(f"{'=' * 44}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: dedup
# ---------------------------------------------------------------------------


def cmd_dedup(args: argparse.Namespace) -> int:
    """Delete duplicates, keeping the first file per group (imgdedup.py)."""
    res = _pipeline(args)
    if res is None:
        print("Nothing to do.")
        return 0
    _root, multi, _threshold = res
    if not multi:
        print("No duplicates (near-duplicates) found.")
        return 0

    dry = args.dry_run
    kept = 0
    deleted = 0
    for g in multi:
        kept += 1
        for p in g[1:]:
            if dry:
                info(f"[DRY RUN] Would delete: {p.name}")
                deleted += 1
                continue
            try:
                p.unlink()
                info(f"Deleted: {p.name}")
                deleted += 1
            except Exception as e:
                err(f"Failed to delete {p}: {e}")

    print(f"\n{'=' * 44}")
    if dry:
        print(f"[DRY RUN] Would keep {kept} file(s), delete {deleted} duplicate(s).")
    else:
        print(f"✓ Kept {kept} file(s), deleted {deleted} duplicate(s).")
    print(f"{'=' * 44}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: keep-one
# ---------------------------------------------------------------------------


def cmd_keep_one(args: argparse.Namespace) -> int:
    """Keep exactly one image per group folder, delete the rest."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"Not a directory: {root}")
        return 1

    try:
        pattern = re.compile(args.pattern)
    except re.error as e:
        err(f"Invalid pattern: {e}")
        return 1

    folders = [p for p in root.iterdir() if p.is_dir() and pattern.match(p.name)]
    info(f"Found {len(folders)} group folder(s) matching /{args.pattern}/")
    if not folders:
        return 0

    if not args.yes:
        print(
            f"WARNING: This will delete images from {len(folders)} folders in {root}."
        )
        print("Only ONE image will be kept per folder. This action cannot be undone!")
        ans = input("Do you want to continue? (yes/no): ").strip().lower()
        if ans not in ("yes", "y"):
            print("Operation cancelled.")
            return 1

    processed = 0
    for folder in folders:
        images = sorted(
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
        if len(images) <= 1:
            info(f"{folder.name}: nothing to do ({len(images)} image(s))")
            continue
        keeper = images[0]
        info(f"{folder.name}: keeping {keeper.name}")
        for p in images[1:]:
            try:
                p.unlink()
                info(f"  Deleted: {p.name}")
            except Exception as e:
                err(f"  Error deleting {p.name}: {e}")
        processed += 1

    print(f"✅ Completed! Processed {processed} folder(s).")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: cluster  (organize_images.py)
# ---------------------------------------------------------------------------


def cmd_cluster(args: argparse.Namespace) -> int:
    """HSV-histogram + raw-pixel features → agglomerative clustering into K groups."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        err(f"Not a directory: {root}")
        return 1
    if not (_require("cv2", "cluster") and _require("numpy", "cluster")):
        return 2

    import numpy as np  # type: ignore

    paths = collect_images(
        root, recursive=True, exclude_parts={"organized_by_similarity"}
    )
    print(f"Scanning directory: {root}")
    print(f"Found {len(paths)} images")
    if not paths:
        print("No images found!")
        return 0

    features: List[Any] = []
    valid: List[Path] = []
    for i, p in enumerate(paths):
        if i % 10 == 0:
            print(f"Processing {i}/{len(paths)}...")
        f = feature_hist(p)
        if f is not None:
            features.append(f)
            valid.append(p)
    print(f"\nSuccessfully processed {len(features)} out of {len(paths)} images")
    if not features:
        print("No valid images to process!")
        return 1

    feats_arr = np.array(features)
    k = min(args.clusters, len(feats_arr))

    def cosine(a: Any, b: Any) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    # Greedy agglomerative merge, faithful to organize_images.py.
    n = len(feats_arr)
    clusters: Dict[int, List[int]] = {i: [i] for i in range(n)}
    centroids: Dict[int, Any] = {i: feats_arr[i].copy() for i in range(n)}
    max_iter = n * 2
    it = 0
    while len(clusters) > k and it < max_iter:
        it += 1
        best_sim = -1.0
        best_pair: Optional[Tuple[int, int]] = None
        keys = list(clusters.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                ki, kj = keys[i], keys[j]
                s = cosine(centroids[ki], centroids[kj])
                if s > best_sim:
                    best_sim = s
                    best_pair = (ki, kj)
        if best_pair is None or best_sim < args.threshold:
            break
        ki, kj = best_pair
        clusters[ki].extend(clusters[kj])
        members = [feats_arr[idx] for idx in clusters[ki]]
        centroids[ki] = np.mean(members, axis=0)
        del clusters[kj]
        del centroids[kj]

    labels = [0] * n
    for t, members in enumerate(clusters.values()):
        for idx in members:
            labels[idx] = t

    num_groups = len(clusters)
    out_dir = root / "organized_by_similarity"
    out_dir.mkdir(exist_ok=True)
    for g in range(num_groups):
        (out_dir / f"group_{g + 1}").mkdir(exist_ok=True)

    print("Organizing files...")
    for path, label in zip(valid, labels):
        dest_dir = out_dir / f"group_{label + 1}"
        dst = dest_dir / path.name
        stem, suffix = path.stem, path.suffix
        cnt = 1
        while dst.exists():
            dst = dest_dir / f"{stem}_{cnt}{suffix}"
            cnt += 1
        try:
            if args.move:
                shutil.move(str(path), str(dst))
            else:
                shutil.copy2(str(path), str(dst))
        except Exception as e:
            err(f"Error copying {path}: {e}")

    print(f"\nDone! Photos organized in: {out_dir}")
    print(f"Organized {len(valid)} images into {num_groups} groups")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _add_pipeline_args(sp: argparse.ArgumentParser) -> None:
    """Flags shared by scan/organize/dedup."""
    sp.add_argument(
        "-d", "--directory", default=".", help="Directory to scan (default: .)"
    )
    sp.add_argument(
        "--method",
        choices=METHODS,
        default="phash",
        help="Feature/hash method (default: phash)",
    )
    sp.add_argument(
        "--hash-size",
        type=int,
        default=None,
        help="Hash size (default: 16 for dct-phash, else 8)",
    )
    sp.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Similarity threshold (default: per-method / 0.9 in similarity mode)",
    )
    sp.add_argument(
        "--mode",
        choices=("hamming", "similarity"),
        default="hamming",
        help="Threshold interpretation (default: hamming distance)",
    )
    sp.add_argument(
        "-r", "--recursive", action="store_true", help="Scan subdirectories recursively"
    )
    sp.add_argument(
        "--workers", type=int, default=4, help="Parallel worker threads (default: 4)"
    )
    sp.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Subdirectory name to skip (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="img_similarity.py",
        description="Unified image similarity / deduplication toolkit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original-script mapping:\n"
            "  dupimg.py                         -> scan --method dct-phash --threshold 4\n"
            "  find_sim_images.py <algo> <dir>   -> scan --method <algo> --threshold 0\n"
            "  folderim.py                       -> organize --method phash --threshold 10\n"
            "  folderimg.py                      -> organize --method multihash --threshold 10\n"
            "  folderize_images.py               -> organize --method phash --hash-size 16 --out _similar_groups\n"
            "  folderize_images_by_similarity.py -> organize --method ahash --mode similarity --threshold 0.95\n"
            "  imgdedup.py <dir> [--remove]      -> dedup --method dhash-custom [--no-dry-run]\n"
            "  keeponeingroups.py                -> keep-one --yes\n"
            "  organize_images.py                -> cluster -k 10 --threshold 0.7\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan ----------------------------------------------------------------
    sp = sub.add_parser(
        "scan", help="Find & report similar/duplicate groups (no file changes)"
    )
    _add_pipeline_args(sp)
    sp.set_defaults(func=cmd_scan)

    # organize ------------------------------------------------------------
    sp = sub.add_parser("organize", help="Group similar images into folders")
    _add_pipeline_args(sp)
    sp.add_argument(
        "--out",
        default="_similar_groups",
        help="Output folder prefix (default: _similar_groups)",
    )
    sp.add_argument(
        "--action",
        choices=("move", "copy"),
        default="move",
        help="How to place images in group folders (default: move)",
    )
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="Preview only (default)"
    )
    grp.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually perform the action",
    )
    sp.set_defaults(dry_run=True)
    sp.set_defaults(func=cmd_organize)

    # dedup ---------------------------------------------------------------
    sp = sub.add_parser("dedup", help="Delete duplicates, keeping first per group")
    _add_pipeline_args(sp)
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="Preview only (default)"
    )
    grp.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually delete duplicates",
    )
    sp.set_defaults(dry_run=True)
    sp.set_defaults(func=cmd_dedup)

    # keep-one ------------------------------------------------------------
    sp = sub.add_parser(
        "keep-one", help="Keep one image per group_*/similar_*/duplicates_* folder"
    )
    sp.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Directory containing group folders (default: .)",
    )
    sp.add_argument(
        "--pattern",
        default=r"^(similar|group|duplicates)_",
        help="Regex matching group folder names "
        r"(default: ^(similar|group|duplicates)_)",
    )
    sp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )
    sp.set_defaults(func=cmd_keep_one)

    # cluster -------------------------------------------------------------
    sp = sub.add_parser(
        "cluster", help="HSV-histogram agglomerative clustering into N groups"
    )
    sp.add_argument(
        "-d", "--directory", default=".", help="Directory to scan (default: .)"
    )
    sp.add_argument(
        "-k", "--clusters", type=int, default=10, help="Number of groups (default: 10)"
    )
    sp.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Cosine-similarity threshold for merging (default: 0.7)",
    )
    sp.add_argument("--move", action="store_true", help="Move files instead of copying")
    sp.set_defaults(func=cmd_cluster)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
