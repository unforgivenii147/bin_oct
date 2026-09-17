#!/data/data/com.termux/files/home/.local/bin/python
"""Recursively convert .json.br files to .json.zst (zstd level 9), in-place."""

from pathlib import Path

import brotli
import zstandard as zstd


def human(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0:
            return f"{n:6.2f} {unit}"
        n /= 1024.0
    return f"{n:6.2f} PiB"


def main() -> None:
    root = Path.cwd()
    files = sorted(p for p in root.rglob("*.json.br") if p.is_file())

    if not files:
        print(f"No .json.br files found under {root}")
        return

    cctx = zstd.ZstdCompressor(level=9)

    total_in = 0
    total_out = 0

    print(f"Found {len(files)} file(s) under {root}\n")
    print(f"{'file':<60} {'br':>12} {'zst':>12} {'diff':>12}  {'%':>7}")
    print("-" * 108)

    for src in files:
        dst = src.with_suffix("")  # strip .br -> .json
        dst = dst.with_suffix(".json.zst")

        try:
            compressed = src.read_bytes()
            raw = brotli.decompress(compressed)
            zst_bytes = cctx.compress(raw)
            dst.write_bytes(zst_bytes)
            src.unlink()
        except Exception as e:
            print(f"ERROR {src}: {e}")
            continue

        br_size = src.stat().st_size if src.exists() else len(compressed)
        br_size = len(compressed)
        zst_size = len(zst_bytes)
        diff = zst_size - br_size
        pct = (diff / br_size * 100) if br_size else 0.0

        total_in += br_size
        total_out += zst_size

        try:
            rel = src.relative_to(root)
        except ValueError:
            rel = src
        rel_str = str(rel)
        if len(rel_str) > 58:
            rel_str = "..." + rel_str[-55:]

        print(
            f"{rel_str:<60} {human(br_size):>12} {human(zst_size):>12} "
            f"{human(diff):>12}  {pct:>6.2f}%"
        )

    print("-" * 108)
    total_diff = total_out - total_in
    total_pct = (total_diff / total_in * 100) if total_in else 0.0
    print(
        f"{'TOTAL (' + str(len(files)) + ' files)':<60} "
        f"{human(total_in):>12} {human(total_out):>12} "
        f"{human(total_diff):>12}  {total_pct:>6.2f}%"
    )


if __name__ == "__main__":
    main()
