#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from dh import TXT_EXT as TEXT_EXTENSIONS, get_nobinary
from joblib import Parallel, delayed

LICENSE_FILE = Path("/sdcard/lic")
WORKERS = 8
CHUNK_SIZE = 8192


@dataclass
class FileStats:
    path: Path
    removed_count: int = 0
    bytes_removed: int = 0
    bytes_processed: int = 0
    error: str | None = None
    modified: bool = False

    def __str__(self):
        rel = self.path.relative_to(Path.cwd())
        if self.error:
            return f"{rel}: ERROR - {self.error}"
        if self.modified:
            return (
                f"{rel}: Processed {self.bytes_processed:,} bytes, "
                f"removed {self.removed_count} occurrence(s) "
                f"({self.bytes_removed:,} bytes)"
            )
        return f"{rel}: No changes needed ({self.bytes_processed:,} bytes)"


def read_license_pattern() -> str:
    try:
        if not LICENSE_FILE.exists():
            raise FileNotFoundError(f"License file not found: {LICENSE_FILE}")
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            pattern = f.read()
        if not pattern.strip():
            raise ValueError("License file is empty")
        return pattern
    except Exception as e:
        print(f"Error reading license file: {e}", file=sys.stderr)
        sys.exit(1)


def find_text_files(directories: list[Path]) -> Iterator[Path]:
    for directory in directories:
        if not directory.exists():
            print(f"Warning: Directory does not exist: {directory}", file=sys.stderr)
            continue
        if directory.is_file():
            if directory.suffix.lower() in TEXT_EXTENSIONS or not directory.suffix:
                yield directory
        else:
            yield from get_nobinary(directory)


def calculate_pattern_fingerprint(pattern: str) -> str:
    return hashlib.sha256(pattern.encode("utf-8")).hexdigest()


def process_file(path: Path, pattern: str, pattern_fingerprint: str) -> FileStats:
    stats = FileStats(path=path)
    try:
        file_size = path.stat().st_size
        stats.bytes_processed = file_size
        if pattern not in path.read_text(encoding="utf-8", errors="ignore"):
            return stats
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, suffix=".tmp"
        ) as temp_file:
            temp_path = Path(temp_file.name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as source:
                    content = source.read()
                    count = content.count(pattern)
                    if count == 0:
                        return stats
                    modified_content = content.replace(pattern, "")
                    temp_file.write(modified_content)
                    temp_file.flush()
                    stats.removed_count = count
                    stats.bytes_removed = len(pattern) * count
                    stats.modified = True
                shutil.move(str(temp_path), str(path))
            except Exception:
                if temp_path.exists():
                    temp_path.unlink()
                raise
    except (OSError, UnicodeDecodeError) as e:
        stats.error = str(e)
    except Exception as e:
        stats.error = f"Unexpected error: {e}"
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Remove multi-line text pattern from files recursively.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s /path/to/dir
  %(prog)s file1.txt file2.txt
  %(prog)s -a /path/to/dir
  %(prog)s --auto-remove
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--auto-remove",
        action="store_true",
        help="Automatically remove found patterns (without confirmation)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=WORKERS,
        help=f"Number of parallel jobs (default: {WORKERS})",
    )
    args = parser.parse_args()
    print(f"Reading pattern from {LICENSE_FILE}...")
    pattern = read_license_pattern()
    pattern_fingerprint = calculate_pattern_fingerprint(pattern)
    print(
        f"Pattern loaded ({len(pattern)} characters, {len(pattern.splitlines())} lines)"
    )
    if not args.paths:
        paths = [Path.cwd()]
    else:
        paths = args.paths
    print("Scanning for files...")
    files = list(find_text_files(paths))
    if not files:
        print("No text files found to process.")
        return
    print(f"Found {len(files)} text file(s) to process")
    if args.dry_run:
        print("\nDRY RUN - No changes will be made\n")
    if args.auto_remove or args.dry_run:
        print("Processing files in parallel...")
        stats_list = Parallel(n_jobs=args.jobs, verbose=1)(
            delayed(process_file)(path, pattern, pattern_fingerprint) for path in files
        )
        print("\n" + "=" * 40)
        print("PROCESSING REPORT")
        print("=" * 40)
        total_files = len(stats_list)
        modified_files = sum(1 for s in stats_list if s.modified)
        total_removed = sum(s.removed_count for s in stats_list)
        total_bytes = sum(s.bytes_removed for s in stats_list)
        total_processed = sum(s.bytes_processed for s in stats_list)
        errors = [s for s in stats_list if s.error]
        for stats in stats_list:
            print(stats)
        print("\n" + "=" * 40)
        print(f"Files processed: {total_files}")
        print(f"Files modified: {modified_files}")
        print(f"Pattern removed: {total_removed} occurrence(s)")
        print(f"Total bytes removed: {total_bytes:,}")
        print(f"Total bytes processed: {total_processed:,}")
        if errors:
            print(f"Errors encountered: {len(errors)}")
    else:
        print("\nDry run mode (no changes will be made). Use -a to apply changes.")
        print("Files that contain the pattern:")
        preview_stats = Parallel(n_jobs=args.jobs, verbose=0)(
            delayed(
                lambda f: (
                    f,
                    (
                        pattern in f.read_text(encoding="utf-8", errors="ignore")
                        if f.stat().st_size < 10 * 1024 * 1024
                        else False
                    ),
                )
            )(path)
            for path in files
        )
        for path, contains in preview_stats:
            if contains:
                rel = path.relative_to(Path.cwd())
                print(f"  {rel}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
