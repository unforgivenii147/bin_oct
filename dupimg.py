#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import shutil
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
HASH_SIZE = 16


def log_verbose(msg: str, level: str = "INFO") -> None:
    if os.environ.get("VERBOSE", "1") == "1":
        print(f"[{level}] {msg}")


def log_action(msg: str) -> None:
    print(msg)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def load_image_cv2(path: str) -> np.ndarray | None:
    try:
        img = cv2.imread(path)
        if img is None:
            return None
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return img
    except Exception as e:
        log_verbose(f"Failed to load {path}: {e}", "WARN")
        return None


def phash_cv2(img: np.ndarray, hash_size: int = HASH_SIZE) -> str:
    if img is None:
        return None
    resized = cv2.resize(img, (hash_size, hash_size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    dct = cv2.dct(np.float32(gray))
    avg = np.mean(dct[:8, :8])
    hash_bits = (dct[:8, :8] > avg).flatten()
    hash_str = "".join(hash_bits.astype(int).astype(str))
    return hash_str


def hamming_distance(hash1: str, hash2: str) -> int:
    if hash1 is None or hash2 is None:
        return float("inf")
    return sum(c1 != c2 for c1, c2 in zip(hash1, hash2, strict=False))


def compute_hash(path: Path) -> tuple[str, str | None]:
    img = load_image_cv2(str(path))
    if img is None:
        return path.name, None
    hash_str = phash_cv2(img)
    return path.name, hash_str


def find_duplicates(hashes: list[tuple[str, str]], threshold: int) -> list[list[str]]:
    groups = []
    used = set()
    for i, (file_i, hash_i) in enumerate(hashes):
        if file_i in used:
            continue
        group = [file_i]
        used.add(file_i)
        for j in range(i + 1, len(hashes)):
            file_j, hash_j = hashes[j]
            if file_j in used:
                continue
            distance = hamming_distance(hash_i, hash_j)
            if distance <= threshold:
                group.append(file_j)
                used.add(file_j)
        if len(group) > 1:
            groups.append(group)
    return groups


def get_file_info(path: Path) -> str:
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        img = load_image_cv2(str(path))
        if img is not None:
            height, width = img.shape[:2]
            return f"{path.name:<50} ({width}x{height}, {size_mb:.2f} MB)"
        else:
            return f"{path.name:<50} ({size_mb:.2f} MB)"
    except Exception:
        return path.name


def move_duplicates_to_folders(
    groups: list[list[str]],
    current_dir: Path,
    output_prefix: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    folders_created = 0
    files_moved = 0
    for group_idx, group in enumerate(sorted(groups, key=len, reverse=True), 1):
        folder_name = f"{output_prefix}_{group_idx:03d}"
        folder_path = current_dir / folder_name
        if not dry_run:
            folder_path.mkdir(exist_ok=True)
            log_verbose(f"Created folder: {folder_name}")
            folders_created += 1
        else:
            log_verbose(f"[DRY RUN] Would create folder: {folder_name}", "INFO")
            folders_created += 1
        for filename in group:
            src = current_dir / filename
            dst = folder_path / filename
            if not src.exists():
                log_verbose(f"Source file not found: {filename}", "WARN")
                continue
            try:
                if not dry_run:
                    shutil.move(str(src), str(dst))
                    log_verbose(f"Moved: {filename} → {folder_name}/")
                    files_moved += 1
                else:
                    log_verbose(
                        f"[DRY RUN] Would move: {filename} → {folder_name}/", "INFO"
                    )
                    files_moved += 1
            except Exception as e:
                log_verbose(f"Failed to move {filename}: {e}", "ERROR")
    return folders_created, files_moved


def main():
    threshold = int(os.environ.get("DUP_HASH_THRESHOLD", "4"))
    num_workers = int(os.environ.get("NUM_WORKERS", cpu_count()))
    verbose = os.environ.get("VERBOSE", "1") == "1"
    output_prefix = os.environ.get("OUTPUT_DIR_PREFIX", "duplicates")
    dry_run = os.environ.get("DRY_RUN", "0") == "1"
    log_verbose("Starting duplicate image finder and organizer")
    log_verbose(f"Threshold: {threshold}, Workers: {num_workers}")
    if dry_run:
        log_verbose("DRY RUN MODE - No files will be moved", "WARN")
    log_verbose(f"Output folder prefix: {output_prefix}")
    current_dir = Path.cwd()
    files = [f for f in current_dir.glob("*") if f.is_file() and is_image(f)]
    if not files:
        log_action("No images found in the current directory.")
        sys.exit(0)
    log_verbose(f"Found {len(files)} image file(s)")
    if verbose:
        for f in files:
            log_verbose(f"  - {f.name}")
    log_verbose(f"Computing hashes with {num_workers} worker(s)...")
    start_time = time.time()
    with Pool(num_workers) as pool:
        hashes = pool.map(compute_hash, files)
    elapsed = time.time() - start_time
    log_verbose(f"Hash computation completed in {elapsed:.2f}s")
    valid_hashes = [(name, h) for name, h in hashes if h is not None]
    failed_count = len(hashes) - len(valid_hashes)
    if failed_count > 0:
        log_verbose(f"{failed_count} file(s) could not be processed", "WARN")
    if not valid_hashes:
        log_action("No readable images found.")
        sys.exit(0)
    log_verbose(f"Grouping {len(valid_hashes)} image(s) by hash similarity...")
    groups = find_duplicates(valid_hashes, threshold)
    if not groups:
        log_action("✓ No duplicates (near-duplicates) found.")
        sys.exit(0)
    log_action(f"\n{'=' * 40}")
    log_action(f"✗ Found {len(groups)} duplicate group(s) (threshold={threshold})")
    log_action(f"{'=' * 40}\n")
    for group_idx, group in enumerate(sorted(groups, key=len, reverse=True), 1):
        log_action(f"Group #{group_idx} ({len(group)} file(s)):")
        log_action("-" * 40)
        for filename in sorted(group):
            path = current_dir / filename
            log_action(f"  • {get_file_info(path)}")
        log_action()
    if dry_run:
        log_action(f"\n{'=' * 40}")
        log_action("[DRY RUN] Preview of operations:")
        log_action(f"{'=' * 40}\n")
    folders_created, files_moved = move_duplicates_to_folders(
        groups, current_dir, output_prefix, dry_run=dry_run
    )
    log_action(f"\n{'=' * 40}")
    if dry_run:
        log_action(
            f"[DRY RUN] Would create {folders_created} folder(s) and move {files_moved} file(s)"
        )
    else:
        log_action(
            f"✓ Created {folders_created} folder(s) and moved {files_moved} file(s)"
        )
    total_dupes = sum(len(g) for g in groups)
    log_action(f"Summary: {len(groups)} group(s), {total_dupes} duplicate file(s)")
    log_action(f"{'=' * 40}\n")


if __name__ == "__main__":
    raise SystemExit(main())
