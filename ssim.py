#!/data/data/com.termux/files/home/.local/bin/python
"""
A script to detect duplicate and similar files in a directory tree.
It uses xxhash for exact duplicate detection and ssdeep for similarity comparison.
Options are provided to copy similar file groups to an output directory or to delete
duplicates while keeping one file per group (move mode).
"""

import argparse
import shutil
from collections.abc import Iterator
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import List

import ssdeep
import xxhash
from loguru import logger
from tqdm import tqdm

EXCLUDE_DIRS: set[str] = {".git", "__pycache__", "node_modules"}


def hash_file(path: Path) -> tuple[str, str | None, str | None]:
    """
    Compute xxhash and ssdeep hashes for a file.

    Args:
        path: Path to the file to hash.

    Returns:
        A tuple of (file path as string, xxhash hexdigest, ssdeep hash).
        On error, the hash values are None.
    """
    try:
        data: bytes = path.read_bytes()
        return str(path), xxhash.xxh64(data).hexdigest(), ssdeep.hash(data)
    except Exception as e:
        logger.error(f"Error hashing {path}: {e}")
        return str(path), None, None


class FileSimilarityDetector:
    """
    Detects duplicate and similar files within a directory tree.

    Attributes:
        cwd: The root directory to scan.
        file_hashes: Mapping from file path to its computed hashes.
        duplicates: Mapping from xxhash to a list of file paths that are exact duplicates.
    """

    def __init__(self, cwd: str = ".") -> None:
        """
        Initialize the detector with a root directory.

        Args:
            cwd: The directory to scan. Defaults to the current directory.
        """
        self.cwd: Path = Path(cwd)
        self.file_hashes: dict[str, dict[str, str]] = {}
        self.duplicates: dict[str, list[str]] = {}

    def scan_files(self) -> Iterator[Path]:
        """
        Yield all non-symlink files in the directory tree, excluding EXCLUDE_DIRS.

        Yields:
            Path objects for each eligible file.
        """
        for path in self.cwd.rglob("*"):
            if path.is_file() and not path.is_symlink():
                if not any(part in EXCLUDE_DIRS for part in path.parts):
                    yield path

    def process_files(self, files: list[Path]) -> None:
        """
        Process files in parallel to compute hashes and find exact duplicates.

        Args:
            files: List of file paths to process.
        """
        print(f"Processing {len(files)} files...")
        with Pool(processes=8) as pool:
            async_results: list[AsyncResult[tuple[str, str | None, str | None]]] = [
                pool.apply_async(hash_file, (f,)) for f in files
            ]
            for async_res in tqdm(
                async_results, total=len(async_results), desc="Hashing"
            ):
                path, xh, sh = async_res.get()
                if not xh or not sh:
                    continue
                self.file_hashes[path] = {"xxhash": xh, "ssdeep": sh}
                self.duplicates.setdefault(xh, []).append(path)

        # Keep only hashes that have more than one file
        self.duplicates = {
            h: paths for h, paths in self.duplicates.items() if len(paths) > 1
        }

    def find_similarity_groups(self, threshold: int) -> list[list[str]]:
        """
        Find groups of similar files using ssdeep comparison, excluding exact duplicates.

        Args:
            threshold: Minimum ssdeep similarity score (0-100) to consider files similar.

        Returns:
            A list of groups, where each group is a list of file paths that are similar.
        """
        excluded: set[str] = {p for group in self.duplicates.values() for p in group}
        candidates: list[str] = [p for p in self.file_hashes if p not in excluded]
        visited: set[str] = set()
        groups: list[list[str]] = []

        for i, p1 in enumerate(tqdm(candidates, desc="Finding Similarities")):
            if p1 in visited:
                continue
            group: list[str] = [p1]
            visited.add(p1)
            h1: str = self.file_hashes[p1]["ssdeep"]
            for p2 in candidates[i + 1 :]:
                if p2 in visited:
                    continue
                if ssdeep.compare(h1, self.file_hashes[p2]["ssdeep"]) >= threshold:
                    group.append(p2)
                    visited.add(p2)
            if len(group) > 1:
                groups.append(group)

        return groups

    def handle_groups(
        self, groups: list[list[str]], *, move: bool, output_dir: str
    ) -> None:
        """
        Handle similarity groups: either copy to output dir or delete duplicates (move mode).

        Args:
            groups: List of similarity groups, each a list of file paths.
            move: If True, keep one file per group and delete the rest.
            output_dir: Directory to copy similar groups into (copy mode only).
        """
        out: Path = Path(output_dir)
        out.mkdir(exist_ok=True)

        for idx, group in enumerate(groups, 1):
            if move:
                # Keep the first file, delete the rest
                for victim in group[1:]:
                    try:
                        Path(victim).unlink()
                        print(f"Deleted {victim}")
                    except Exception as e:
                        logger.error(f"Failed to delete {victim}: {e}")
            else:
                grp_dir: Path = out / f"similarity_group_{idx}"
                grp_dir.mkdir(exist_ok=True)
                for p in group:
                    try:
                        shutil.copy2(p, grp_dir / Path(p).name)
                        print(f"Copied {p} to {grp_dir}")
                    except Exception as e:
                        logger.error(f"Failed to copy {p}: {e}")

    def print_duplicates(self) -> None:
        """Log information about exact duplicate files."""
        if not self.duplicates:
            return
        print("=" * 40)
        print("DUPLICATES (100% identical)")
        for h, paths in self.duplicates.items():
            print(f"\nHash: {h}")
            for p in paths:
                print(f"  - {p}")
        print("-" * 40)


def main() -> None:
    """Parse command-line arguments and run the file similarity detection."""
    parser = argparse.ArgumentParser(description="Detect duplicate and similar files")
    parser.add_argument(
        "threshold", type=int, default=70, help="Similarity threshold (0-100)"
    )
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Keep one file per similarity group and delete the rest",
    )
    parser.add_argument(
        "-o", "--output", default="output", help="Output directory (copy mode only)"
    )
    args: argparse.Namespace = parser.parse_args()

    detector: FileSimilarityDetector = FileSimilarityDetector()
    files: list[Path] = list(detector.scan_files())
    if not files:
        print("No files found.")
        return

    detector.process_files(files)
    groups: list[list[str]] = detector.find_similarity_groups(args.threshold)

    if groups:
        detector.handle_groups(groups, move=args.move, output_dir=args.output)
        print(f"Processed {len(groups)} similarity groups.")
    else:
        print("No similar (non-identical) files found.")

    detector.print_duplicates()


if __name__ == "__main__":
    raise SystemExit(main())
