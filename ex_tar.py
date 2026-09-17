#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import tarfile
import tempfile
import time
from pathlib import Path

import zstandard as zstd


def get_dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def extract_zst_file(archive_path, extract_path):
    output_path = extract_path / archive_path.stem
    with Path(archive_path).open("rb") as compressed_file:
        dctx = zstd.ZstdDecompressor()
        with Path(output_path).open("wb") as output_file:
            dctx.copy_stream(compressed_file, output_file)
    return output_path


def extract_tar_zst(archive_path, extract_path) -> None:
    with Path(archive_path).open("rb") as compressed_file:
        dctx = zstd.ZstdDecompressor()
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as temp_tar:
            dctx.copy_stream(compressed_file, temp_tar)
            temp_tar_path = temp_tar.name
    try:
        with tarfile.open(temp_tar_path, "r") as tar:
            tar.extractall(path=extract_path, filter="data")
    finally:
        Path(temp_tar_path).unlink()


def extract_tar_xz(archive_path, extract_path) -> None:
    with tarfile.open(archive_path, "r:xz") as tar:
        tar.extractall(path=extract_path, filter="data")


def process_archive(
    archive_path: Path,
    dry_run: bool = False,
    keep_original: bool = False,
    quiet: bool = False,
):
    if not archive_path.exists():
        if not quiet:
            print(f"Error: File {archive_path} does not exist")
        return False, 0, 0
    archive_size = archive_path.stat().st_size
    extract_path = archive_path.parent
    archive_name = archive_path.name
    extracted_files = []
    is_tar_zst = archive_name.endswith(".tar.zst")
    is_tar_xz = archive_name.endswith(".tar.xz")
    is_standalone_zst = archive_name.endswith(".zst") and not is_tar_zst
    if not (is_tar_zst or is_tar_xz or is_standalone_zst):
        if not quiet:
            print(
                f"Skipping unsupported file: {archive_path} (not .zst, .tar.zst, or .tar.xz)"
            )
        return False, 0, 0
    try:
        if dry_run:
            if not quiet:
                print(f"[DRY RUN] Would extract: {archive_path}")
            return True, archive_size, 0
        if not quiet:
            print(f"Extracting: {archive_path}")
        if is_standalone_zst:
            output_file = extract_zst_file(archive_path, extract_path)
            extracted_files = [output_file]
        elif is_tar_zst:
            extract_tar_zst(archive_path, extract_path)
            extracted_files = ["multiple files (tar contents)"]
        elif is_tar_xz:
            extract_tar_xz(archive_path, extract_path)
            extracted_files = ["multiple files (tar contents)"]
        extracted_size = 0
        if extracted_files and extracted_files[0] != "multiple files (tar contents)":
            for path in extracted_files:
                if path.exists():
                    extracted_size += path.stat().st_size
        else:
            current_time = time.time()
            for item in extract_path.rglob("*"):
                if (
                    item.is_file()
                    and item != archive_path
                    and current_time - item.stat().st_ctime < 60
                ):
                    extracted_size += item.stat().st_size
        if not keep_original:
            archive_path.unlink()
            if not quiet:
                print(f"  ✓ Extracted and removed original: {archive_name}")
        elif not quiet:
            print(f"  ✓ Extracted (kept original): {archive_name}")
        return True, archive_size, extracted_size
    except Exception as e:
        if not quiet:
            print(f"  ✗ Error processing {archive_path}: {e}")
        return False, 0, 0


def find_archives(directory: Path) -> list[Path]:
    directory = Path(directory).resolve()
    archives = [
        zst_file
        for zst_file in directory.rglob("*.zst")
        if not zst_file.name.endswith(".tar.zst")
    ]
    archives.extend(directory.rglob("*.tar.zst"))
    archives.extend(directory.rglob("*.tar.xz"))
    return sorted(set(archives))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="""Extract .zst, .tar.zst, and .tar.xz archives.
If a filename is provided, process only that file.
If no argument, recursively search current directory.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="File to extract or directory to search (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without actually extracting",
    )
    parser.add_argument(
        "--keep-original",
        "-k",
        action="store_true",
        help="Keep original archive files after extraction",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress output"
    )
    args = parser.parse_args()
    if args.target:
        target_path = Path(args.target).resolve()
        if not target_path.exists():
            print(f"Error: {target_path} does not exist")
            return 1
        is_single_file = target_path.is_file()
    else:
        target_path = Path.cwd().resolve()
        is_single_file = False
    if is_single_file:
        if not args.quiet:
            print(f"Processing single file: {target_path}")
        parent_dir = target_path.parent
        before = get_dir_size(parent_dir)
        success, arch_size, ext_size = process_archive(
            target_path, args.dry_run, args.keep_original, args.quiet
        )
        if not args.dry_run and success:
            after = get_dir_size(parent_dir)
            size_change = after - before
            size_change_mb = size_change / (1024 * 1024)
            print(f"\n{'=' * 40}")
            print(f"Summary for {target_path.name}:")
            print(f"  Archive size: {arch_size / (1024 * 1024):.2f} MB")
            print(f"  Extracted size: {ext_size / (1024 * 1024):.2f} MB")
            if arch_size > 0:
                print(f"  Compression ratio: {ext_size / arch_size:.2f}:1")
            print(f"  Directory size change: {size_change_mb:+.2f} MB")
        elif args.dry_run:
            print(f"\n{'=' * 40}")
            print(f"DRY RUN: Would extract {target_path.name}")
        return 0 if success else 1
    if not args.quiet:
        print(f"Recursively scanning {target_path} for archives...")
    archives = find_archives(target_path)
    if not archives:
        print("No supported archives found.")
        return 0
    if not args.quiet:
        print(f"Found {len(archives)} archives to process")
        zst_count = sum(
            1
            for a in archives
            if a.suffix == ".zst" and not a.name.endswith(".tar.zst")
        )
        tar_zst_count = sum(1 for a in archives if a.name.endswith(".tar.zst"))
        tar_xz_count = sum(1 for a in archives if a.name.endswith(".tar.xz"))
        if zst_count:
            print(f"  - Standalone .zst: {zst_count}")
        if tar_zst_count:
            print(f"  - .tar.zst: {tar_zst_count}")
        if tar_xz_count:
            print(f"  - .tar.xz: {tar_xz_count}")
    before = get_dir_size(target_path)
    processed_count = 0
    failed_count = 0
    total_archive_size = 0
    total_extracted_size = 0
    for archive in archives:
        success, arch_size, ext_size = process_archive(
            archive, args.dry_run, args.keep_original, args.quiet
        )
        if success:
            processed_count += 1
            total_archive_size += arch_size
            total_extracted_size += ext_size
        else:
            failed_count += 1
    if not args.dry_run:
        after = get_dir_size(target_path)
        size_change = after - before
        size_change_mb = size_change / (1024 * 1024)
        print(f"\n{'=' * 40}")
        print("Summary:")
        print(f"  Processed: {processed_count} archives")
        if failed_count > 0:
            print(f"  Failed: {failed_count} archives")
        print(f"  Initial directory size: {before / (1024 * 1024):.2f} MB")
        print(f"  Final directory size:   {after / (1024 * 1024):.2f} MB")
        print(f"  Size change:            {size_change_mb:+.2f} MB")
        if total_archive_size > 0:
            compression_ratio = total_extracted_size / total_archive_size
            print(f"  Average compression ratio: {compression_ratio:.2f}:1")
            print(
                f"  Space saved by compression: {total_archive_size / (1024 * 1024):.2f} MB"
            )
    else:
        print(f"\n{'=' * 40}")
        print("DRY RUN SUMMARY:")
        print(f"  Would process: {len(archives)} archives")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
