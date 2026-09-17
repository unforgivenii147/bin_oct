#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

from PIL import Image

for png_path in Path(".").rglob("*.png"):
    if png_path.is_file():
        jpg_path = png_path.with_suffix(".jpg")
        try:
            img = Image.open(png_path).convert("RGB")
            img.save(jpg_path, "JPEG")
            png_path.unlink()
            print(f"Converted and deleted: {png_path} -> {jpg_path}")
        except Exception as e:
            print(f"Failed to convert {png_path}: {e}")
