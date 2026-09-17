#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from gzip import compress as gzip_compress
from pathlib import Path

from dh import get_files, mpf3
from lzma_mt import decompress


def process_file(path: Path) -> tuple[str, bool, str]:
    path = Path(path)
    if path.is_symlink():
        print("symlink")
        return (str(path), False, "Error: symlink")
    gz_path = path.with_suffix(".gz")
    try:
        data = path.read_bytes()
        decompressed = decompress(data, threads=4)
        compressed = gzip_compress(decompressed, compresslevel=9)
        gz_path.write_bytes(compressed)
        if gz_path.exists() and gz_path.stat().st_size > 0:
            path.unlink()
            original_size = path.stat().st_size if path.exists() else 0
            new_size = gz_path.stat().st_size
            ratio = new_size / original_size * 40 if original_size > 0 else 0
            return (
                str(path),
                True,
                f"Converted to {gz_path.name} ({original_size} -> {new_size} bytes, {ratio:.1f}%)",
            )
        return (str(path), False, "Output file is empty or missing")
    except Exception as e:
        if gz_path.exists():
            gz_path.unlink()
        return (str(path), False, f"Error: {e!s}")


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".xz"])
    if not files:
        print("No .xz files found to convert.")
        return
    results = mpf3(process_file, files)
    success_count = 0
    failure_count = 0
    total_original = 0
    total_new = 0
    print("\n" + "=" * 40)
    print("CONVERSION RESULTS")
    print("-" * 40)
    for path, success, message in results:
        if success:
            success_count += 1
            print(f"✓ {message}")
            if "bytes" in message:
                try:
                    parts = message.split("(")[1].split(")")
                    sizes = parts[0].split("->")
                    total_original += int(sizes[0].strip().split()[0])
                    total_new += int(sizes[1].strip().split()[0])
                except:
                    pass
        else:
            failure_count += 1
            print(f"✗ {path}: {message}", file=sys.stderr)
    print("-" * 40)
    print(f"Summary: {success_count} successful, {failure_count} failed")
    print(f"Total files processed: {len(results)}")
    if success_count > 0 and total_original > 0:
        savings = (1 - total_new / total_original) * 40
        print(
            f"Total space saved: {total_original - total_new:,} bytes ({savings:.1f}%)"
        )
        print(f"Original total: {total_original:,} bytes")
        print(f"New total: {total_new:,} bytes")
    if success_count > 0:
        print("\nNote: Original .xz files have been removed.")


if __name__ == "__main__":
    raise SystemExit(main())
