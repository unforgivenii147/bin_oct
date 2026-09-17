#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python script that prepares images for Tesseract OCR by converting them to
black-and-white, denoised, high-contrast images in place. The script must:
- Use loguru for logging instead of the standard logging module or print.
- Use pathlib exclusively for path handling.
- Use multiprocessing.Pool.apply_async with a fixed pool of 8 workers for concurrency.
- Avoid any CLI arguments controlling parallelism (no --workers, --jobs, etc.).
- Include complete type hints on all functions, methods, arguments, return types,
  module-level constants, and variables; the code must pass strict type checking.
- Include a module docstring, function docstrings, and a CLI using argparse with
  positional paths (files or folders), a -r/--recursive flag, and -v/--verbose.
- Support OpenCV if available, otherwise Pillow; exit with an error if neither is installed.
- Process common image extensions: .png, .jpg, .jpeg, .tiff, .tif, .bmp, .gif.
- Return exit code 0 if all images succeed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

from loguru import logger

try:
    import cv2  # type: ignore[import-not-found]

    USE_CV2: bool = True
    print("Using OpenCV for image processing")
except ImportError:
    try:
        from PIL import (
            Image,
            ImageEnhance,  # type: ignore[import-not-found]
            ImageFilter,
        )

        USE_CV2 = False
        print("OpenCV not found, using Pillow for image processing")
    except ImportError:
        logger.error("Neither OpenCV nor Pillow found. Please install at least one.")
        sys.exit(1)

IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"}
POOL_SIZE: int = 8


def process_image_cv2(image_path: Path) -> bool:
    """Process a single image using OpenCV (grayscale, adaptive threshold, denoise).

    Args:
        image_path: Path to the image file to process in place.

    Returns:
        True if processing succeeded, False otherwise.
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Failed to read image: {image_path}")
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)
        cv2.imwrite(str(image_path), denoised)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error processing {image_path}: {e}")
        return False


def process_image_pil(image_path: Path) -> bool:
    """Process a single image using Pillow (grayscale, contrast, sharpen, blur, threshold).

    Args:
        image_path: Path to the image file to process in place.

    Returns:
        True if processing succeeded, False otherwise.
    """
    try:
        with Image.open(image_path) as img:
            if img.mode != "L":
                img = img.convert("L")
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            threshold = 128
            img = img.point(lambda p: p > threshold and 255)
            img.save(str(image_path))
            return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error processing {image_path}: {e}")
        return False


def process_image(image_path: Path) -> tuple[Path, bool]:
    """Process a single image using the available backend.

    Args:
        image_path: Path to the image file.

    Returns:
        A tuple of the image path and a boolean indicating success.
    """
    logger.debug(f"Processing: {image_path}")
    if USE_CV2:
        success = process_image_cv2(image_path)
    else:
        success = process_image_pil(image_path)
    return (image_path, success)


def find_images(paths: list[Path], recursive: bool = False) -> list[Path]:
    """Find all supported image files under the given paths.

    Args:
        paths: A list of files or directories to search.
        recursive: Whether to search directories recursively.

    Returns:
        A deduplicated list of image file paths.
    """
    image_files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(path)
        elif path.is_dir():
            if recursive:
                for ext in IMAGE_EXTENSIONS:
                    image_files.extend(path.rglob(f"*{ext}"))
                    image_files.extend(path.rglob(f"*{ext.upper()}"))
            else:
                for ext in IMAGE_EXTENSIONS:
                    image_files.extend(path.glob(f"*{ext}"))
                    image_files.extend(path.glob(f"*{ext.upper()}"))
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in image_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files


def process_images_parallel(image_files: list[Path]) -> dict[str, int]:
    """Process images in parallel using a fixed-size multiprocessing pool.

    Args:
        image_files: A list of image file paths to process.

    Returns:
        A dictionary with counts of successful and failed processings.
    """
    if not image_files:
        logger.warning("No image files found to process")
        return {"success": 0, "failed": 0}

    workers: int = min(POOL_SIZE, len(image_files))
    print(f"Processing {len(image_files)} images using {workers} workers")

    results: dict[str, int] = {"success": 0, "failed": 0}
    with Pool(processes=workers) as pool:
        async_results = [
            (path, pool.apply_async(process_image, (path,))) for path in image_files
        ]
        for path, async_result in async_results:
            try:
                _, success = async_result.get()
                if success:
                    results["success"] += 1
                    print(f"✓ Processed: {path}")
                else:
                    results["failed"] += 1
                    logger.error(f"✗ Failed: {path}")
            except Exception as e:  # noqa: BLE001
                results["failed"] += 1
                logger.error(f"✗ Error processing {path}: {e}")
    return results


def main() -> int:
    """Run the CLI for preparing images for Tesseract OCR.

    Returns:
        Exit code 0 if all images succeeded, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Prepare images for Tesseract OCR (in-place processing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s image1.png image2.jpg     # Process specific files\n  %(prog)s /path/to/folder           # Process images in folder\n  %(prog)s -r /path/to/folder        # Process images recursively\n  %(prog)s                           # Process all images in current directory\n  %(prog)s -r                        # Process all images recursively\n        ",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or folders to process (if empty, process current directory)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Process subdirectories recursively",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    paths: list[Path] = args.paths if args.paths else [Path.cwd()]
    if not args.paths:
        print(f"No input specified, processing current directory: {Path.cwd()}")

    image_files: list[Path] = find_images(paths, args.recursive)
    if not image_files:
        logger.error("No supported image files found")
        print(f"Supported extensions: {', '.join(sorted(IMAGE_EXTENSIONS))}")
        return 1

    print(f"Found {len(image_files)} image(s) to process")
    results: dict[str, int] = process_images_parallel(image_files)
    print("=" * 40)
    print("Processing complete:")
    print(f"  ✓ Success: {results['success']}")
    print(f"  ✗ Failed:  {results['failed']}")
    print(f"  Total:     {len(image_files)}")
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
