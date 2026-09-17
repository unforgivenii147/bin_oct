#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import Iterator
from multiprocessing import Pool, cpu_count
from pathlib import Path

from dh import TXT_EXT

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SpinnerProgressReporter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.last_count = 0
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_index = 0

    def __call__(self, current_path: str, file_count: int):
        if not self.verbose:
            return
        if file_count - self.last_count >= 500:
            self.last_count = file_count
            self.spinner_index = (self.spinner_index + 1) % len(self.spinner)
            path_display = (
                current_path[:60] + "..." if len(current_path) > 60 else current_path
            )
            msg = f"\r{self.spinner[self.spinner_index]} Files: {file_count:8d} | {path_display}"
            print(msg, end="", flush=True)


def memory_efficient_file_finder(
    root_dir: str,
    extensions: set[str],
    progress_callback=None,
    skip_symlinks: bool = True,
    skip_mount_points: bool = True,
) -> Iterator[Path]:
    extensions_lower = {ext.lower() for ext in extensions}
    visited_inodes = set()
    file_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(
            root_dir, topdown=True, onerror=lambda e: logger.warning(f"Walk error: {e}")
        ):
            try:
                dir_stat = os.stat(dirpath)
                dir_inode = (dir_stat.st_dev, dir_stat.st_ino)
                if skip_symlinks and dir_inode in visited_inodes:
                    dirnames[:] = []
                    continue
                visited_inodes.add(dir_inode)
                if skip_mount_points and dirpath != root_dir:
                    try:
                        root_stat = os.stat(root_dir)
                        if dir_stat.st_dev != root_stat.st_dev:
                            dirnames[:] = []
                            continue
                    except OSError:
                        pass
            except (OSError, FileNotFoundError):
                dirnames[:] = []
                continue
            if progress_callback and file_count % 500 == 0:
                progress_callback(dirpath, file_count)
            for filename in filenames:
                try:
                    path = Path(dirpath) / filename
                    if path.suffix.lower() in extensions_lower:
                        file_count += 1
                        yield path
                except (OSError, FileNotFoundError):
                    continue
    except KeyboardInterrupt:
        print("Traversal interrupted by user")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during traversal: {e}")


def is_text_file(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        if not chunk:
            return True
        if b"\x00" in chunk:
            return False
        try:
            chunk.decode("utf-8")
            return True
        except UnicodeDecodeError:
            for encoding in ["latin-1", "iso-8859-1", "cp1252"]:
                try:
                    chunk.decode(encoding)
                    return True
                except (UnicodeDecodeError, LookupError):
                    continue
            return False
    except (OSError, PermissionError):
        return None


def check_file(path: Path) -> tuple[Path, str, bool, str]:
    try:
        extension = path.suffix.lower()
        is_text = is_text_file(path)
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or "unknown"
        return (path, extension, is_text, mime_type)
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
        return (path, path.suffix.lower(), None, "error")


def validate_extensions(
    root_dir: str = "/", num_workers: int | None = None, verbose: bool = True
) -> dict:
    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)
    root_path = Path(root_dir)
    if not root_path.exists():
        logger.error(f"Root directory {root_dir} does not exist")
        return {}
    print(f"Starting filesystem traversal from {root_dir}...")
    print(f"Looking for extensions: {sorted(TXT_EXT)}")
    print(f"Using {num_workers} worker processes")
    print()
    progress = SpinnerProgressReporter(verbose=verbose)
    matching_files = list(
        memory_efficient_file_finder(
            root_dir,
            TXT_EXT,
            progress_callback=progress,
            skip_symlinks=True,
            skip_mount_points=True,
        )
    )
    print()
    print(f"Found {len(matching_files)} files with target extensions")
    if not matching_files:
        logger.warning("No files found with specified extensions")
        return {
            "total_files": 0,
            "text_files": 0,
            "binary_files": 0,
            "access_errors": 0,
            "mismatches": [],
            "by_extension": {},
        }
    print("Checking file types (parallel processing)...")
    with Pool(num_workers) as pool:
        results = pool.map(check_file, matching_files)
    text_count = 0
    binary_count = 0
    error_count = 0
    mismatches = []
    by_extension = {}
    for path, ext, is_text, mime_type in results:
        if ext not in by_extension:
            by_extension[ext] = {"text": 0, "binary": 0, "error": 0, "files": []}
        by_extension[ext]["files"].append(
            {"path": str(path), "is_text": is_text, "mime_type": mime_type}
        )
        if is_text is True:
            text_count += 1
            by_extension[ext]["text"] += 1
        elif is_text is False:
            binary_count += 1
            by_extension[ext]["binary"] += 1
            mismatches.append(
                {"path": str(path), "extension": ext, "mime_type": mime_type}
            )
        else:
            error_count += 1
            by_extension[ext]["error"] += 1
    return {
        "total_files": len(matching_files),
        "text_files": text_count,
        "binary_files": binary_count,
        "access_errors": error_count,
        "mismatches": mismatches,
        "by_extension": by_extension,
    }


def print_report(results: dict):
    print("\n" + "=" * 40)
    print("TEXT EXTENSION VALIDATION REPORT")
    print("-" * 40)
    print("\nSummary:")
    print(f"  Total files found:    {results['total_files']}")
    print(f"  Actual text files:    {results['text_files']}")
    print(f"  Binary files:         {results['binary_files']}")
    print(f"  Access errors:        {results['access_errors']}")
    if results["mismatches"]:
        print(
            f"\n⚠️  MISMATCHES FOUND: {len(results['mismatches'])} files with .txt extension are NOT text files"
        )
        print("-" * 40)
        for i, mismatch in enumerate(results["mismatches"][:20], 1):
            print(f"  {i}. {mismatch['path']}")
            print(
                f"     └─ Extension: {mismatch['extension']} | MIME: {mismatch['mime_type']}"
            )
        if len(results["mismatches"]) > 20:
            print(f"  ... and {len(results['mismatches']) - 20} more")
    else:
        print("\n✓ No mismatches found! All files match their extensions.")
    print("\nBreakdown by extension:")
    print("-" * 40)
    for ext, stats in sorted(results["by_extension"].items()):
        print(
            f"  {ext:12} - Text: {stats['text']:6}  Binary: {stats['binary']:6}  Errors: {stats['error']:6}"
        )
    print("\n" + "=" * 40)


if __name__ == "__main__":
    import sys

    root_dir = sys.argv[1] if len(sys.argv) > 1 else "/data/data/com.termux"
    try:
        results = validate_extensions(root_dir, verbose=True)
        print_report(results)
        sys.exit(1 if results["mismatches"] else 0)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation stopped by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
