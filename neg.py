#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import logging
import sys
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

from PIL import Image

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".gif",
}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def invert_image(image_path: Path, dry_run: bool = False) -> tuple[Path, bool]:
    try:
        if dry_run:
            print(f"[DRY RUN] Would invert: {image_path}")
            return (image_path, True)
        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            inverted = img.point(lambda p: 255 - p)
            inverted.save(image_path, quality=95, optimize=True)
        print(f"✓ Inverted: {image_path}")
        return (image_path, True)
    except Exception as e:
        logger.error(f"✗ Failed to process {image_path}: {e}")
        return (image_path, False)


def find_images(root_dir: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        image_files = [
            f for f in root_dir.rglob("*") if f.is_file() and is_image_file(f)
        ]
    else:
        image_files = [
            f for f in root_dir.iterdir() if f.is_file() and is_image_file(f)
        ]
    return sorted(image_files)


def main():
    parser = argparse.ArgumentParser(
        description="Convert images to negative (invert colors) recursively in place",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s ./photos                 # Invert all images recursively in ./photos\n  %(prog)s ./images -n 4            # Use 4 parallel processes\n  %(prog)s ./images --dry-run       # Preview what would be processed\n  %(prog)s ./images --no-recursive  # Only process current directory\n        ",
    )
    parser.add_argument(
        "directory", type=str, help="Directory containing images to invert"
    )
    parser.add_argument(
        "-n",
        "--processes",
        type=int,
        default=None,
        help="Number of parallel processes (default: CPU count)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not process subdirectories recursively",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually modifying files",
    )
    parser.add_argument(
        "--extensions",
        type=str,
        nargs="+",
        help="Additional file extensions to process (e.g., .jpg .png)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    root_dir = Path(args.directory)
    if not root_dir.exists():
        logger.error(f"Directory does not exist: {root_dir}")
        sys.exit(1)
    if not root_dir.is_dir():
        logger.error(f"Path is not a directory: {root_dir}")
        sys.exit(1)
    if args.extensions:
        for ext in args.extensions:
            if not ext.startswith("."):
                ext = "." + ext
            SUPPORTED_EXTENSIONS.add(ext.lower())
    recursive = not args.no_recursive
    print(
        f"Scanning {('recursively' if recursive else 'non-recursively')} in: {root_dir}"
    )
    image_files = find_images(root_dir, recursive)
    if not image_files:
        logger.warning("No image files found to process")
        sys.exit(0)
    print(f"Found {len(image_files)} image(s) to process")
    num_processes = args.processes or cpu_count()
    print(f"Using {num_processes} process(es)")
    if args.dry_run:
        print("DRY RUN MODE - No files will be modified")
    invert_func = partial(invert_image, dry_run=args.dry_run)
    with Pool(processes=num_processes) as pool:
        results = pool.map(invert_func, image_files)
    successful = sum((1 for _, success in results if success))
    failed = len(results) - successful
    print(f"\n{'=' * 40}")
    print("Processing complete!")
    print(f"✓ Successful: {successful}")
    if failed > 0:
        logger.warning(f"✗ Failed: {failed}")
    print(f"Total processed: {len(results)}")


if __name__ == "__main__":
    raise SystemExit(main())
