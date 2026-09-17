#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from pathlib import Path


def optimize_pngs_recursively() -> None:
    total_original_size = 0
    total_optimized_size = 0
    for png_file in Path().rglob("*.png"):
        original_size = png_file.stat().st_size
        total_original_size += original_size
        subprocess.run(
            ["pngcrush", "-ow", "-rem", "allb", "-brute", "-reduce", str(png_file)],
            check=True,
        )
        optimized_size = png_file.stat().st_size
        size_change = original_size - optimized_size
        print(f"Processed: {png_file}")
        print(
            f"  Original: {original_size} bytes, Optimized: {optimized_size} bytes, Change: {size_change} bytes"
        )
        total_optimized_size += optimized_size
    total_reduction = total_original_size - total_optimized_size
    print("\n--- Summary ---")
    print(f"Total original size: {total_original_size} bytes")
    print(f"Total optimized size: {total_optimized_size} bytes")
    print(f"Total reduction: {total_reduction} bytes")


if __name__ == "__main__":
    optimize_pngs_recursively()
