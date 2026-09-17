#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
import textwrap
from collections.abc import Generator
from pathlib import Path

import lzma_mt

ARCHIVE_EXTENSIONS = {
    ".zip",
    ".br",
    ".xz",
    ".gz",
    ".bz2",
    ".bz3",
    ".zst",
    ".7z",
    ".lz4",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".Z",
    ".lz",
    ".lzma",
    ".xza",
}
MEDIA_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".webm",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".mp3",
    ".aac",
    ".flac",
    ".wav",
    ".m4a",
    ".opus",
    ".ogg",
    ".wma",
    ".alac",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".tiff",
    ".ico",
    ".heic",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".iso",
    ".img",
}
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", ".env", "node_modules"}


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def get_files_to_process(root_dir: Path, compress: bool) -> Generator[Path, None, None]:
    if compress:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file):
                if file.suffix.lower() not in ARCHIVE_EXTENSIONS and not is_media_file(
                    file
                ):
                    yield file
    else:
        for file in root_dir.rglob("*"):
            if (
                file.is_file()
                and not should_exclude(file)
                and file.suffix.lower() == ".xz"
            ):
                yield file


def compress_file(
    path: Path, preset: int = 9, threads: int = 4, remove_orig: bool = True
) -> tuple[Path, bool, str, int, int]:
    try:
        with open(path, "rb") as f:
            data = f.read()
        original_size = len(data)
        compressed = lzma_mt.compress(data, preset=preset, threads=threads)
        len(compressed)
        output_path = path.parent / (path.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        space_freed = 0
        if remove_orig:
            path.unlink()
            space_freed = original_size
        return (
            path,
            True,
            f"Compressed to {output_path.name}",
            original_size,
            space_freed,
        )
    except Exception as e:
        return path, False, f"Error: {e!s}", 0, 0


def decompress_file(
    path: Path, remove_orig: bool = True
) -> tuple[Path, bool, str, int, int]:
    try:
        if path.suffix.lower() != ".xz":
            return path, False, "Error: Not an .xz file", 0, 0
        with open(path, "rb") as f:
            data = f.read()
        compressed_size = len(data)
        decompressed = lzma_mt.decompress(data)
        output_path = path.parent / path.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        space_freed = 0
        if remove_orig:
            path.unlink()
            space_freed = compressed_size
        return (
            path,
            True,
            f"Decompressed to {output_path.name}",
            compressed_size,
            space_freed,
        )
    except Exception as e:
        return path, False, f"Error: {e!s}", 0, 0


def format_bytes(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def process_files(
    root_dir: Path, compress: bool, preset: int, threads: int, remove_orig: bool = True
):
    action = "Compressing" if compress else "Decompressing"
    print(f"{action} files in {root_dir}...")
    print(f"Preset: {preset}, Threads: {threads}")
    print()
    total_success = 0
    total_failed = 0
    total_space_freed = 0
    total_original_size = 0
    processed = 0
    files_generator = get_files_to_process(root_dir, compress)
    total_files = sum(1 for _ in files_generator)
    if total_files == 0:
        action = "compress" if compress else "decompress"
        print(f"No files found to {action}")
        return
    for path in get_files_to_process(root_dir, compress):
        processed += 1
        pct = processed / total_files * 40
        if compress:
            path, success, message, orig_size, space_freed = compress_file(
                path, preset, threads, remove_orig
            )
        else:
            path, success, message, orig_size, space_freed = decompress_file(
                path, remove_orig
            )
        status = "✓" if success else "✗"
        rel_path = path.relative_to(root_dir)
        print(f"[{pct:5.1f}%] {processed}/{total_files} {status} {rel_path}: {message}")
        if success:
            total_success += 1
            total_space_freed += space_freed
            if compress:
                total_original_size += orig_size
        else:
            total_failed += 1
    print(f"\n{'─' * 40}")
    print(f"Total successful: {total_success}")
    print(f"Total failed: {total_failed}")
    if compress and total_original_size > 0:
        print(f"Total original size: {format_bytes(total_original_size)}")
        if total_space_freed > 0:
            print(f"Disk space freed: {format_bytes(total_space_freed)}")


def main():
    parser = argparse.ArgumentParser(
        description="Recursively compress or decompress files using lzma_mt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python compress_files.py
              python compress_files.py -c --preset 6 --threads 8
              python compress_files.py -d /path/to/files
              python compress_files.py --keep-orig
            Excluded by default:
              - Directories: .git, __pycache__, .venv, venv, node_modules
              - Archives: .zip, .br, .xz, .gz, .bz2, .bz3, .zst, .7z, .lz4, etc.
              - Media: .mp4, .mkv, .mp3, .jpg, .png, .pdf, .exe, etc.
        """),
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no -d specified)",
    )
    parser.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress .xz files"
    )
    parser.add_argument(
        "--preset",
        type=int,
        default=9,
        choices=range(10),
        help="Compression preset 0-9 (default: 9)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Threads per compression job (default: 4)",
    )
    parser.add_argument(
        "--keep-orig",
        action="store_true",
        help="Keep original files after compression/decompression",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    args = parser.parse_args()
    if args.compress and args.decompress:
        print("Error: Cannot specify both -c and -d")
        sys.exit(1)
    compress_mode = args.compress or not args.decompress
    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory")
        sys.exit(1)
    process_files(
        root_dir,
        compress=compress_mode,
        preset=args.preset,
        threads=args.threads,
        remove_orig=not args.keep_orig,
    )


if __name__ == "__main__":
    raise SystemExit(main())
