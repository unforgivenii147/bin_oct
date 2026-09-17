#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that in-place preprocesses all supported images under
the current working directory using OpenCV (or Pillow fallback), runs OCR with
pytesseract, writes .txt sidecar files, and processes images concurrently with
a fixed multiprocessing.Pool of 8 workers using apply_async, logging progress
via loguru, using pathlib for all path operations, and including full type
annotations and docstrings throughout.
"""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path
from typing import Any, Union

import numpy as np
import pytesseract
from loguru import logger

try:
    import cv2

    HAS_CV2: bool = True
except ImportError:
    HAS_CV2 = False
    from PIL import Image, ImageEnhance, ImageFilter

SUPPORTED_EXT: set[str] = {".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"}
BASE_DIR: Path = Path.cwd()
POOL_SIZE: int = 8

ImageType = Union[np.ndarray, "Image.Image"]


def deskew(image: np.ndarray) -> np.ndarray:
    """
    Deskew an OpenCV image using its minimum-area rectangle angle.

    Args:
        image: Binary or grayscale OpenCV image.

    Returns:
        The deskewed image, or the original if no coordinates are found.
    """
    if HAS_CV2:
        coords = np.column_stack(np.where(image > 0))
        if coords.size == 0:
            return image
        angle = cv2.minAreaRect(coords)[-1]
        angle = -(90 + angle) if angle < -45 else -angle
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(
            image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
    return image


def preprocess_image_cv2(img_path: Path) -> np.ndarray | None:
    """
    Preprocess an image using OpenCV.

    Args:
        img_path: Path to the source image.

    Returns:
        The preprocessed image as a numpy array, or None on failure.
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
    )
    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    return deskew(cleaned)


def preprocess_image_pillow(img_path: Path) -> Image.Image | None:
    """
    Preprocess an image using Pillow as a fallback.

    Args:
        img_path: Path to the source image.

    Returns:
        The preprocessed PIL image, or None on failure.
    """
    try:
        img = Image.open(str(img_path))
        if img.mode != "L":
            img = img.convert("L")
        w, h = img.size
        img = img.resize((w * 2, h * 2), Image.Resampling.BICUBIC)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        img = img.point(lambda p: 255 if p > 128 else 0)
        img = img.filter(ImageFilter.SHARPEN)
        return img
    except Exception:
        return None


def preprocess_image(img_path: Path) -> ImageType | None:
    """
    Preprocess an image using OpenCV if available, otherwise Pillow.

    Args:
        img_path: Path to the source image.

    Returns:
        The preprocessed image, or None on failure.
    """
    if HAS_CV2:
        return preprocess_image_cv2(img_path)
    return preprocess_image_pillow(img_path)


def should_skip(path: Path) -> bool:
    """
    Determine whether a path should be skipped based on extension.

    Args:
        path: Path to check.

    Returns:
        True if the path's extension is not in SUPPORTED_EXT.
    """
    return path.suffix.lower() not in SUPPORTED_EXT


def save_processed_image(img: ImageType, img_path: Path) -> None:
    """
    Save a processed image back to disk.

    Args:
        img: The processed image (numpy array or PIL image).
        img_path: Destination path.

    Raises:
        ValueError: If the image type is unsupported.
    """
    if HAS_CV2 and isinstance(img, np.ndarray):
        cv2.imwrite(str(img_path), img)
    elif not HAS_CV2 and not isinstance(img, np.ndarray):
        img.save(str(img_path))
    else:
        raise ValueError("Unsupported image format")


def process_single_image(image_path: Path) -> dict[str, Any]:
    """
    Preprocess an image, overwrite it, and write a .txt sidecar with OCR text.

    Args:
        image_path: Path to the image to process.

    Returns:
        A result dictionary with keys: path, success, error, size_before, size_after.
    """
    result: dict[str, Any] = {
        "path": str(image_path),
        "success": False,
        "error": None,
        "size_before": 0,
        "size_after": 0,
    }
    try:
        result["size_before"] = image_path.stat().st_size
        processed = preprocess_image(image_path)
        if processed is None:
            result["error"] = "Failed to process image"
            return result
        save_processed_image(processed, image_path)
        txt_path = image_path.with_suffix(".txt")
        text = pytesseract.image_to_string(processed, config="--oem 1 --psm 6")
        txt_path.write_text(text, encoding="utf-8")
        result["size_after"] = image_path.stat().st_size
        result["success"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


def get_image_files() -> list[Path]:
    """
    Collect all supported image files under BASE_DIR recursively.

    Returns:
        A list of image file paths.
    """
    image_files: list[Path] = []
    for path in BASE_DIR.rglob("*"):
        if path.is_file() and not should_skip(path):
            image_files.append(path)
    return image_files


def process() -> None:
    """
    Run the full preprocessing + OCR pipeline over all discovered images
    using a fixed multiprocessing.Pool of POOL_SIZE workers.
    """
    if not HAS_CV2:
        logger.warning(
            "OpenCV not found, using Pillow as fallback (limited functionality)"
        )

    image_files = get_image_files()
    total_images = len(image_files)
    if total_images == 0:
        print("No images found to process.")
        return

    print(f"📊 Found {total_images} images to process")
    print(f"⚡ Using {POOL_SIZE} workers for parallel processing")
    print("🔄 Processing images in-place...\n")

    processed_count = 0
    error_count = 0
    total_before = 0
    total_after = 0

    pool = multiprocessing.Pool(processes=POOL_SIZE)
    try:
        async_results = [
            (path, pool.apply_async(process_single_image, (path,)))
            for path in image_files
        ]
        for path, async_result in async_results:
            try:
                result = async_result.get()
                if result["success"]:
                    processed_count += 1
                    total_before += result["size_before"]
                    total_after += result["size_after"]
                    status = "✅"
                else:
                    error_count += 1
                    status = "❌"
                relative = path.relative_to(BASE_DIR)
                print(
                    f"{status} [{processed_count + error_count}/{total_images}] {relative}"
                )
                if result.get("error"):
                    logger.warning(f"   ⚠️ Error: {result['error']}")
            except Exception as e:
                error_count += 1
                logger.error(
                    f"❌ [{processed_count + error_count}/{total_images}] {path.name}: {e}"
                )
    finally:
        pool.close()
        pool.join()

    print("=" * 40)
    print("📊 Processing Summary:")
    print(f"   ✅ Successfully processed: {processed_count} images")
    print(f"   ❌ Errors: {error_count} images")
    print(f"   📁 Total images: {total_images}")
    if processed_count > 0:
        size_reduction = (
            (total_before - total_after) / total_before * 100 if total_before > 0 else 0
        )
        print(f"   📦 Total size before: {total_before / (1024 * 1024):.2f} MB")
        print(f"   📦 Total size after: {total_after / (1024 * 1024):.2f} MB")
        print(f"   📉 Size reduction: {size_reduction:.1f}%")
    print("-" * 40)


def main() -> None:
    """Entry point: prompt for confirmation and run the processing pipeline."""
    logger.warning("⚠️  WARNING: This script will MODIFY original image files in-place!")
    logger.warning("⚠️  NO BACKUPS will be created.")
    logger.warning("⚠️  CTRL+C to cancel, ENTER to continue...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user.")
        sys.exit(0)
    process()


if __name__ == "__main__":
    main()
