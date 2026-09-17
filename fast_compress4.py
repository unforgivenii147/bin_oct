#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

import zstandard as zstd


def walk_files(directory: Path, pattern: str = "*") -> Iterator[tuple[Path, Path]]:
    for path in directory.rglob(pattern):
        if not path.is_file():
            continue
        if path.suffix == ".zst":
            continue
        output_path = path.with_suffix(path.suffix + ".zst")
        if output_path.exists():
            print(f"Skipping {path} - output already exists", file=sys.stderr)
            continue
        yield path, output_path


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int = 3,
    threads: int = 4,
    chunk_size: int = 1024 * 1024,
    remove_original: bool = True,
) -> bool:
    try:
        compressor = zstd.ZstdCompressor(level=level, threads=threads)
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            with compressor.stream_writer(outfile) as stream_writer:
                while True:
                    chunk = infile.read(chunk_size)
                    if not chunk:
                        break
                    stream_writer.write(chunk)
        if output_path.exists() and output_path.stat().st_size > 0:
            original_size = input_path.stat().st_size
            compressed_size = output_path.stat().st_size
            ratio = compressed_size / original_size * 40 if original_size > 0 else 0
            if remove_original:
                input_path.unlink()
                print(f"✓ Compressed & removed: {input_path} -> {output_path}")
            else:
                print(f"✓ Compressed: {input_path} -> {output_path}")
            print(
                f"  Size: {original_size:,} -> {compressed_size:,} bytes ({ratio:.1f}%)"
            )
            return True
        else:
            raise RuntimeError("Compression produced empty or invalid file")
    except Exception as e:
        print(f"✗ Failed to compress {input_path}: {e}", file=sys.stderr)
        if output_path.exists():
            output_path.unlink()
        return False


def decompress_file(
    input_path: Path,
    output_path: Path | None = None,
    chunk_size: int = 1024 * 1024,
    remove_original: bool = True,
) -> bool:
    if not input_path.suffix == ".zst":
        print(f"Skipping {input_path} - not a .zst file", file=sys.stderr)
        return False
    if output_path is None:
        output_path = input_path.with_suffix("")
    if output_path.exists():
        print(f"Skipping {input_path} - output already exists", file=sys.stderr)
        return False
    try:
        decompressor = zstd.ZstdDecompressor()
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            with decompressor.stream_reader(infile) as stream_reader:
                while True:
                    chunk = stream_reader.read(chunk_size)
                    if not chunk:
                        break
                    outfile.write(chunk)
        if remove_original:
            input_path.unlink()
            print(f"✓ Decompressed & removed: {input_path} -> {output_path}")
        else:
            print(f"✓ Decompressed: {input_path} -> {output_path}")
        return True
    except Exception as e:
        print(f"✗ Failed to decompress {input_path}: {e}", file=sys.stderr)
        if output_path.exists():
            output_path.unlink()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Recursively compress/decompress files using zstandard"
    )
    parser.add_argument("directory", type=str, help="Root directory to process")
    parser.add_argument(
        "--decompress",
        "-d",
        action="store_true",
        help="Decompress .zst files instead of compressing",
    )
    parser.add_argument(
        "--level",
        "-l",
        type=int,
        default=3,
        help="Compression level (1-22, default: 3)",
    )
    parser.add_argument(
        "--threads", "-t", type=int, default=4, help="Number of threads (default: 4)"
    )
    parser.add_argument(
        "--pattern",
        "-p",
        type=str,
        default="*",
        help="File pattern to match (default: *)",
    )
    parser.add_argument(
        "--chunk-size",
        "-c",
        type=int,
        default=1024 * 1024,
        help="Chunk size in bytes (default: 1MB)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without actually doing it",
    )
    parser.add_argument(
        "--keep-original",
        "-k",
        action="store_true",
        help="Keep original files (don't remove them)",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory)
    if not root_dir.exists():
        print(f"Error: Directory '{root_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    if not root_dir.is_dir():
        print(f"Error: '{root_dir}' is not a directory", file=sys.stderr)
        sys.exit(1)
    remove_original = not args.keep_original
    print(
        f"{'Decompressing' if args.decompress else 'Compressing'} files in: {root_dir}"
    )
    print(f"Pattern: {args.pattern}")
    print(f"Remove original: {'Yes' if remove_original else 'No'}")
    if not args.decompress:
        print(f"Level: {args.level}, Threads: {args.threads}")
    processed = 0
    failed = 0
    if args.decompress:
        for path, _ in walk_files(root_dir, f"*{args.pattern}*.zst"):
            if args.dry_run:
                print(
                    f"[DRY RUN] Would decompress & {'remove' if remove_original else 'keep'}: {path}"
                )
            elif decompress_file(
                path, chunk_size=args.chunk_size, remove_original=remove_original
            ):
                processed += 1
            else:
                failed += 1
    else:
        for input_path, output_path in walk_files(root_dir, args.pattern):
            if args.dry_run:
                print(
                    f"[DRY RUN] Would compress & {
                        'remove' if remove_original else 'keep'
                    }: {input_path} -> {output_path}"
                )
            elif compress_file(
                input_path,
                output_path,
                level=args.level,
                threads=args.threads,
                chunk_size=args.chunk_size,
                remove_original=remove_original,
            ):
                processed += 1
            else:
                failed += 1
    print(f"\n{'=' * 40}")
    print(
        f"Completed: {processed} files {'decompressed' if args.decompress else 'compressed'}"
    )
    if failed > 0:
        print(f"Failed: {failed} files")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
