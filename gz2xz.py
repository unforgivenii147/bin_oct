#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import gzip
import sys
from pathlib import Path

from dh import mpf3
from lzma_mt import compress


def process_file(path: Path) -> tuple[str, bool, str]:
    path = Path(path)
    xz_path = path.with_suffix(".xz")
    try:
        with gzip.open(path, "rb") as file:
            data = file.read()
        compressed = compress(data, preset=9, threads=4)
        xz_path.write_bytes(compressed)
        if xz_path.exists() and xz_path.stat().st_size > 0:
            path.unlink()
            original_size = path.stat().st_size if path.exists() else 0
            new_size = xz_path.stat().st_size
            ratio = new_size / original_size * 40 if original_size > 0 else 0
            return (
                str(path),
                True,
                f"Converted to {xz_path.name} ({original_size} -> {new_size} bytes, {ratio:.1f}%)",
            )
        else:
            return (str(path), False, "Output file is empty or missing")
    except Exception as e:
        if xz_path.exists():
            xz_path.unlink()
        return (str(path), False, f"Error: {e!s}")


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".gz"])
    if not files:
        print("No .gz files found to convert.")
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
        print("\nNote: Original .gz files have been removed.")


if __name__ == "__main__":
    raise SystemExit(main())
