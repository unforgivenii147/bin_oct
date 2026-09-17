#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import glob

from PIL import Image


def reduce_image_size(image_path, scale_factor=0.75) -> None:
    try:
        with Image.open(image_path) as img:
            new_width = int(img.width * scale_factor)
            new_height = int(img.height * scale_factor)
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)
            resized_img.save(image_path, optimize=True, quality=85)
            print(
                f"Reduced: {image_path} ({img.width}x{img.height} -> {new_width}x{new_height})"
            )
    except Exception as e:
        print(f"Error processing {image_path}: {e!s}")


def main() -> None:
    image_files = []
    for extension in image_extensions:
        image_files.extend(glob.glob(extension))
        image_files.extend(glob.glob(extension.upper()))
    if not image_files:
        print("No image files found in current directory.")
        return
    print(f"Found {len(image_files)} image file(s) to process...")
    for image_file in image_files:
        reduce_image_size(image_file)
    print("All images processed!")


if __name__ == "__main__":
    raise SystemExit(main())
