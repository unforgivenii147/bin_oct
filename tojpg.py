#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

try:
    import cv2
    import numpy as np

    USE_CV2 = True
except ImportError:
    from PIL import Image

    USE_CV2 = False
SUPPORTED_FORMATS = {".png", ".bmp", ".tiff", ".webp", ".ico", ".jpg", ".jpeg"}


def convert_to_jpg(path: str) -> bool:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_FORMATS:
        print(f"Skipping: {path.name} (Unsupported format or not a file)")
        return False
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return True
    output_path = path.with_suffix(".jpg")
    if output_path.exists():
        response = (
            input(f"'{output_path.name}' exists. Overwrite? (y/n): ").strip().lower()
        )
        if response != "y":
            return False
    try:
        if USE_CV2:
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if img is None:
                print(f"Error: Could not decode {path.name}")
                return False
            if img.shape[2] == 4:
                b, g, r, a = cv2.split(img)
                white_bg = np.full(img.shape[:2], 255, dtype=np.uint8)
                alpha = a.astype(float) / 255.0
                img_b = (
                    b.astype(float) * alpha + white_bg.astype(float) * (1 - alpha)
                ).astype(np.uint8)
                img_g = (
                    g.astype(float) * alpha + white_bg.astype(float) * (1 - alpha)
                ).astype(np.uint8)
                img_r = (
                    r.astype(float) * alpha + white_bg.astype(float) * (1 - alpha)
                ).astype(np.uint8)
                final_img = cv2.merge((img_b, img_g, img_r))
            else:
                final_img = img
            success = cv2.imwrite(
                str(output_path), final_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95]
            )
        else:
            img = Image.open(path)
            if img.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                final_img = background
            else:
                final_img = img
            final_img.save(output_path, "JPEG", quality=95)
            success = True
        if success:
            path.unlink()
            print(f"Successfully converted '{path.name}' to jpg.")
            return True
        print(f"Failed to write '{output_path.name}'")
        return False
    except Exception as e:
        print(f"Error converting '{path.name}': {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <image_file>")
        sys.exit(1)
    if convert_to_jpg(sys.argv[1]):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
