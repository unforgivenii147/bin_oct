#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

SKIPPED_PATHS = []


def hash_file(path: Path, chunk_size: int = 8192) -> str:
    sha = hashlib.sha256()
    try:
        get_size = path.stat().st_size
        with (
            Path(path).open("rb") as f,
            tqdm(
                total=get_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"Hashing {path.name}",
                leave=False,
            ) as pbar,
        ):
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha.update(chunk)
                pbar.update(len(chunk))
    except PermissionError:
        SKIPPED_PATHS.append(str(path))
        return None
    except OSError:
        SKIPPED_PATHS.append(str(path))
        return None
    return sha.hexdigest()


def collect_all_files(directory: Path):
    all_files = []
    for root, _dirs, files in os.walk(directory, onerror=lambda e: None):
        for f in files:
            full_path = Path(root) / f
            all_files.append(full_path)
    return all_files


def find_duplicate_files(directory: str):
    directory = Path(directory)
    if not directory.exists():
        raise ValueError(msg)
    all_files = collect_all_files(directory)
    duplicates = defaultdict(list)
    print(f"📁 Scanning {len(all_files)} files...\n")
    for path in tqdm(all_files, desc="Overall Progress", unit="file"):
        file_hash = hash_file(path)
        if file_hash:
            duplicates[file_hash].append(str(path))
    return {h: paths for h, paths in duplicates.items() if len(paths) > 1}


def print_duplicates(dups: dict) -> None:
    if not dups:
        print("🎉 No duplicates found!")
        return
    print("\n🔍 Duplicate Files Found:\n")
    for i, (h, paths) in enumerate(dups.items(), start=1):
        print(f"Group {i} (hash={h[:12]}...):")
        for p in paths:
            print(f"   • {p}")
        print("-" * 40)


def export_to_json(dups: dict, output_path="duplicates.json") -> None:
    with Path(output_path).open("w", encoding="utf-8") as f:
        json.dump(dups, f, indent=2)
    print(f"📦 Results exported to {output_path}")


def print_skipped_paths() -> None:
    if not SKIPPED_PATHS:
        return
    print("\n⚠️  Skipped (permission denied):")
    for p in SKIPPED_PATHS:
        print(f"   • {p}")


if __name__ == "__main__":
    folder = input("Enter folder path to scan: ").strip()
    duplicates = find_duplicate_files(folder)
    print_duplicates(duplicates)
    print_skipped_paths()
    if duplicates:
        save = input("Export results to JSON? (y/n): ").lower().strip()
        if save == "y":
            export_to_json(duplicates)
