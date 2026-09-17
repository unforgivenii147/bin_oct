#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
import tarfile
from pathlib import Path

import zstandard as zstd


def create_archive_streaming_optimized():
    current_dir = Path.cwd()
    dir_name = current_dir.name
    parent_dir = current_dir.parent
    if str(current_dir) == "/" or str(current_dir) == str(Path.home()):
        print("Error: Cannot archive root or home directory", file=sys.stderr)
        sys.exit(1)
    archive_path = parent_dir / f"{dir_name}.tar.zst"
    if archive_path.exists():
        response = (
            input(f"Archive '{archive_path}' already exists. Overwrite? (y/n): ")
            .strip()
            .lower()
        )
        if response not in ["y", "yes"]:
            print("Operation cancelled.")
            sys.exit(1)
    try:
        compressor = zstd.ZstdCompressor(level=3, threads=0)
        print(f"Creating archive: {archive_path}")
        print("Collecting files...")
        files_to_archive = []
        for item in current_dir.rglob("*"):
            if ".git" in item.parts:
                continue
            if item.name.endswith(".tar.zst"):
                continue
            files_to_archive.append(item)
        if not files_to_archive:
            print("No files to archive.", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files_to_archive)} items to archive")
        print("Compressing...")
        with (
            open(archive_path, "wb") as f_out,
            compressor.stream_writer(f_out) as zstd_writer,
            tarfile.open(fileobj=zstd_writer, mode="w|") as tar,
        ):
            for item in files_to_archive:
                try:
                    arcname = item.relative_to(parent_dir)
                    if item.is_symlink() or item.is_file() or item.is_dir():
                        tar.add(item, arcname=arcname, recursive=False)
                    else:
                        tar.add(item, arcname=arcname, recursive=False)
                except (OSError, PermissionError) as e:
                    print(f"Warning: Could not add {item}: {e}", file=sys.stderr)
                    continue
        if archive_path.exists() and archive_path.stat().st_size > 0:
            archive_size = archive_path.stat().st_size
            print(f"Archive created successfully: {archive_size:,} bytes")
            response = (
                input(f"Remove original directory '{current_dir}'? (y/n): ")
                .strip()
                .lower()
            )
            if response in ["y", "yes"]:
                print("Removing original directory...")
                shutil.rmtree(current_dir)
                print("Done.")
            else:
                print("Original directory preserved.")
        else:
            print("Error: Archive creation failed", file=sys.stderr)
            if archive_path.exists():
                archive_path.unlink()
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        if archive_path.exists():
            archive_path.unlink()
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if archive_path.exists():
            archive_path.unlink()
        sys.exit(1)


def verify_archive(archive_path):
    try:
        decompressor = zstd.ZstdDecompressor()
        with (
            open(archive_path, "rb") as f,
            decompressor.stream_reader(f) as zstd_reader,
            tarfile.open(fileobj=zstd_reader, mode="r|") as tar,
        ):
            for member in tar:
                print(
                    f"{member.name} ({'dir' if member.isdir() else 'file'}, size: {
                        member.size
                    }, mode: {oct(member.mode)})"
                )
    except Exception as e:
        print(f"Verification failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Create compressed tar.zst archive of current directory"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify archive after creation"
    )
    parser.add_argument(
        "--no-remove",
        action="store_true",
        help="Don't prompt to remove original directory",
    )
    args = parser.parse_args()
    create_archive_streaming_optimized()
    if args.verify:
        current_dir = Path.cwd()
        archive_path = current_dir.parent / f"{current_dir.name}.tar.zst"
        if archive_path.exists():
            print("\nVerifying archive...")
            verify_archive(archive_path)
