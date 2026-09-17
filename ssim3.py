#!/data/data/com.termux/files/home/.local/bin/python
"""
Detect duplicate and similar files within a directory tree using xxhash for exact
duplicates and ssdeep for fuzzy similarity. Uses a fixed multiprocessing.Pool of 8
workers for hashing, logs via loguru, and supports both copy and move (delete
duplicates) modes. CLI: `script.py THRESHOLD [-m] [-o OUTPUT]`.
"""

import argparse
import shutil
from collections import defaultdict
from collections.abc import Iterator
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import List

import ssdeep  # type: ignore[import-untyped]
import xxhash
from loguru import logger
from tqdm import tqdm

EXCLUDE_DIRS: set[str] = {".git", "__pycache__", "node_modules"}

HashResult = tuple[str, str | None, str | None]


def hash_file(path: Path) -> HashResult:
    """
    Compute xxhash and ssdeep digests for the given file.

    Args:
        path: File to hash.

    Returns:
        A tuple ``(path_str, xxhash_hex, ssdeep_hash)``. On error, the hash
        fields are ``None``.
    """
    try:
        data: bytes = path.read_bytes()
        return str(path), xxhash.xxh64(data).hexdigest(), ssdeep.hash(data)
    except Exception as exc:
        logger.warning(f"Failed to hash {path}: {exc}")
        return str(path), None, None


class FileSimilarityDetector:
    """
    Detect exact duplicates (via xxhash) and fuzzy similarity groups (via ssdeep).

    Attributes:
        cwd: Root directory being scanned.
        file_hashes: Mapping of file path string to its computed hashes.
        duplicates: Mapping of xxhash hex to the list of paths sharing that hash.
    """

    def __init__(self, cwd: str = ".") -> None:
        """
        Initialize the detector.

        Args:
            cwd: Directory to scan. Defaults to the current directory.
        """
        self.cwd: Path = Path(cwd)
        self.file_hashes: dict[str, dict[str, str]] = {}
        self.duplicates: defaultdict[str, list[str]] = defaultdict(list)

    def scan_files(self) -> Iterator[Path]:
        """
        Yield every non-symlink regular file below ``self.cwd``, skipping
        directories listed in :data:`EXCLUDE_DIRS`.

        Yields:
            ``Path`` objects for eligible files.
        """
        for root, dirs, files in self.cwd.walk():
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                path: Path = root / name
                if not path.is_symlink():
                    yield path

    def process_files(self, files: list[Path]) -> None:
        """
        Hash the given files in parallel (8 workers) and populate
        :attr:`file_hashes` and :attr:`duplicates`.

        Args:
            files: List of file paths to hash.
        """
        print(f"Processing {len(files)} files...")
        with Pool(processes=8) as pool:
            async_results: list[AsyncResult[HashResult]] = [
                pool.apply_async(hash_file, (f,)) for f in files
            ]
            for async_res in tqdm(
                async_results, total=len(async_results), desc="Hashing"
            ):
                path, xh, sh = async_res.get()
                if not xh or not sh:
                    continue
                self.file_hashes[path] = {"xxhash": xh, "ssdeep": sh}
                self.duplicates[xh].append(path)

        self.duplicates = defaultdict(
            list,
            {h: paths for h, paths in self.duplicates.items() if len(paths) > 1},
        )

    def find_similarity_groups(self, threshold: int) -> list[list[str]]:
        """
        Group files whose ssdeep similarity score is at or above ``threshold``,
        excluding files already flagged as exact duplicates.

        Args:
            threshold: Minimum ssdeep score (0-100) to treat files as similar.

        Returns:
            A list of groups, each group a list of file paths.
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
        Act on each similarity group.

        In move mode, keep the first file of each group and delete the rest.
        In copy mode, copy every member of each group into
        ``output_dir/similarity_group_N/``.

        Args:
            groups: Similarity groups from :meth:`find_similarity_groups`.
            move: If ``True``, delete duplicates instead of copying.
            output_dir: Destination directory for copy mode.
        """
        out: Path = Path(output_dir)
        out.mkdir(exist_ok=True)

        for idx, group in enumerate(groups, 1):
            if move:
                for victim in group[1:]:
                    try:
                        Path(victim).unlink()
                        print(f"Deleted {victim}")
                    except Exception as exc:
                        logger.error(f"Failed to delete {victim}: {exc}")
            else:
                grp_dir: Path = out / f"similarity_group_{idx}"
                grp_dir.mkdir(exist_ok=True)
                for p in group:
                    try:
                        shutil.copy2(p, grp_dir / Path(p).name)
                    except Exception as exc:
                        logger.error(f"Failed to copy {p}: {exc}")

    def print_duplicates(self) -> None:
        """Log every exact-duplicate group (if any) in a readable block."""
        if not self.duplicates:
            return
        print("=" * 40)
        print("DUPLICATES (100% identical)")
        for h, paths in self.duplicates.items():
            print(f"Hash: {h}")
            for p in paths:
                print(f"  - {p}")
        print("-" * 40)


def main() -> None:
    """Parse CLI arguments and run the duplicate/similarity pipeline."""
    parser = argparse.ArgumentParser(description="Detect duplicate and similar files")
    parser.add_argument("threshold", type=int, help="Similarity threshold (0-100)")
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Keep one file per similarity group and delete the rest",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output directory (copy mode only)",
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
