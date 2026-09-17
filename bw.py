#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def analyze_image(
    path: Path, dark_threshold=50, ratio_threshold=0.6
) -> tuple[str, float]:
    with Image.open(path) as img:
        img = img.convert("RGB")
        pixels = img.getdata()
        total = len(pixels)
        dark_count = 0
        for r, g, b in pixels:
            brightness = 0.299 * r + 0.587 * g + 0.114 * b
            if brightness < dark_threshold:
                dark_count += 1
        dark_ratio = dark_count / total
        if dark_ratio > ratio_threshold:
            return "Mostly Dark", dark_ratio
        if dark_ratio < 1 - ratio_threshold:
            return "Mostly Bright", dark_ratio
        return "Mixed", dark_ratio


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: script.py <image>")
        sys.exit(1)
    img_path = Path(sys.argv[1])
    result, ratio = analyze_image(img_path)
    print(f"{img_path.name}: {result}")
    print(f"Dark pixel ratio: {ratio:.2f}%")
