#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that strips EXIF metadata from image files in parallel.

The script should:
- Accept file and/or directory paths as positional CLI arguments (default: current directory).
- Recursively discover image files by extension (.jpg, .jpeg, .png, .tiff, .tif, .bmp, .webp) unless --no-recursive is set.
- Allow overriding the extension list via --extensions.
- Support an optional --backup flag that writes a ".backup" copy of each file before modifying it.
- Support a --verbose flag for per-file logging and a --no-size-report flag to skip folder size reporting.
- Process images concurrently using multiprocessing.Pool.apply_async with a fixed pool of 8 workers (no CLI option to change worker count).
- For each image: open with PIL, rebuild the pixel data into a fresh image object without EXIF, re-encode it (JPEG quality=95 optimize=True; PNG optimize=True), and overwrite the original file.
- Report per-file size changes, aggregate summary statistics, and per-folder size deltas.
- Use loguru for all logging, pathlib for all filesystem operations, full type annotations throughout, and include docstrings for the module and every function.
- Import helper functions fsz (format size) and gsz (get size) from a local module named `dh`.
"""

from __future__ import annotations

import argparse
import io
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any

from dh import fsz, gsz
from loguru import logger
from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS: list[str] = [
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
]

FIXED_WORKERS: int = 8

# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def strip_exif_single(
    image_path: Path,
    backup: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Strip EXIF metadata from a single image file.

    Args:
        image_path: Path to the image file to process.
        backup: If True, write a ``.backup`` copy before modifying the file.
        verbose: If True, emit detailed per-file log messages.

    Returns:
        A dictionary describing the result with keys: ``path``, ``success``,
        ``original_size``, ``new_size``, ``message``, ``backup_created``.
    """
    result: dict[str, Any] = {
        "path": image_path,
        "success": False,
        "original_size": 0,
        "new_size": 0,
        "message": "",
        "backup_created": False,
    }

    try:
        original_size: int = image_path.stat().st_size
        result["original_size"] = original_size

        with Image.open(image_path) as img:
            if backup:
                backup_path: Path = image_path.with_suffix(
                    image_path.suffix + ".backup"
                )
                backup_path.write_bytes(image_path.read_bytes())
                result["backup_created"] = True
                if verbose:
                    logger.debug(f"📋 Backup: {backup_path.name}")

            img_without_exif: Image.Image = Image.new(img.mode, img.size)
            img_without_exif.putdata(list(img.getdata()))

            buffer: io.BytesIO = io.BytesIO()
            format_kwargs: dict[str, Any] = {"format": img.format}

            if img.format == "JPEG":
                format_kwargs["quality"] = 95
                format_kwargs["optimize"] = True
            elif img.format == "PNG":
                format_kwargs["optimize"] = True

            if img.format == "JPEG":
                img_without_exif.save(
                    buffer,
                    format=img.format,
                    quality=95,
                    optimize=True,
                    exif=None,
                )
            else:
                try:
                    img_without_exif.save(buffer, **format_kwargs, exif=None)
                except TypeError:
                    img_without_exif.save(buffer, **format_kwargs)

            new_size: int = buffer.tell()
            result["new_size"] = new_size

            buffer.seek(0)
            image_path.write_bytes(buffer.getvalue())
            result["success"] = True

            size_change: int = new_size - original_size
            percent_change: float = size_change / original_size * 100

            if verbose:
                print(f"✅ {image_path.name}")
                print(
                    f"   {fsz(original_size)} → {fsz(new_size)} "
                    f"({percent_change:+.1f}%)"
                )

            result["message"] = (
                f"Stripped EXIF: {size_change:+.0f}B ({percent_change:+.1f}%)"
            )

    except Exception as e:
        result["success"] = False
        result["message"] = f"Error: {e!s}"
        if verbose:
            logger.error(f"❌ {image_path.name}: {e!s}")

    return result


def process_image_file(
    image_path: Path,
    backup: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Worker entry point that processes a single image file.

    Args:
        image_path: Path to the image file.
        backup: Whether to create a backup before modifying.
        verbose: Whether to log verbosely.

    Returns:
        The result dictionary from :func:`strip_exif_single`.
    """
    return strip_exif_single(image_path, backup, verbose)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def find_image_files(
    paths: list[str],
    extensions: list[str],
    recursive: bool = True,
) -> list[Path]:
    """Find image files under the given paths matching the extensions.

    Args:
        paths: List of file or directory path strings to search.
        extensions: List of file extensions (with or without leading dot).
        recursive: If True, search directories recursively.

    Returns:
        A sorted list of unique :class:`Path` objects for matching files.
    """
    image_files: list[Path] = []

    normalized: list[str] = [
        (ext if ext.startswith(".") else f".{ext}") for ext in extensions
    ]
    all_extensions: set[str] = set()
    for ext in normalized:
        all_extensions.add(ext.lower())
        all_extensions.add(ext.upper())

    for path_str in paths:
        path: Path = Path(path_str)

        if not path.exists():
            logger.warning(f"⚠️  Path does not exist: {path}")
            continue

        if path.is_file():
            if not all_extensions or path.suffix in all_extensions:
                image_files.append(path)
        elif path.is_dir():
            if recursive:
                for ext in all_extensions:
                    image_files.extend(path.glob(f"**/*{ext}"))
            else:
                for ext in all_extensions:
                    image_files.extend(path.glob(f"*{ext}"))
        else:
            logger.warning(f"⚠️  Unknown path type: {path}")

    return sorted(set(image_files))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI.

    Returns:
        The configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description="Strip EXIF data from image files with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s image1.jpg image2.png
  %(prog)s /path/to/images
  %(prog)s file.jpg -b
  %(prog)s . --no-recursive
        """,
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        help="Create backup files (.backup) before stripping EXIF",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not process subdirectories recursively",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=DEFAULT_EXTENSIONS,
        help=(
            "File extensions to process "
            "(default: .jpg .jpeg .png .tiff .tif .bmp .webp)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for each file",
    )
    parser.add_argument(
        "--no-size-report",
        action="store_true",
        help="Skip folder size change report",
    )

    return parser


def main() -> int:
    """Run the CLI entry point.

    Returns:
        Exit code (0 on success).
    """
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    # Fixed worker pool of 8.
    max_workers: int = FIXED_WORKERS
    logger.debug(
        f"Fixed worker count: {max_workers} (CPU count reported: {cpu_count()})"
    )

    recursive: bool = not args.no_recursive
    image_files: list[Path] = find_image_files(args.paths, args.extensions, recursive)

    if not image_files:
        print("ℹ️  No image files found.")
        return 0

    dirs: set[Path] = set()
    initial_sizes: dict[Path, int] = {}

    if not args.no_size_report:
        for img in image_files:
            dirs.add(img.parent)
        for dir_path in dirs:
            initial_sizes[dir_path] = gsz(dir_path)

    print(f"📸 Found {len(image_files)} image file(s)")
    print(f"🔧 Using {max_workers} parallel worker(s)")
    print(f"💾 Backup: {'Yes' if args.backup else 'No'}")
    print(f"📁 Recursive: {'Yes' if recursive else 'No'}")
    print("-" * 40)

    results: list[dict[str, Any]] = []
    processed: int = 0

    with Pool(processes=max_workers) as pool:
        async_results: list[tuple[Path, Any]] = [
            (
                img,
                pool.apply_async(
                    process_image_file,
                    args=(img, args.backup, args.verbose),
                ),
            )
            for img in image_files
        ]

        for img, async_result in async_results:
            processed += 1
            try:
                result: dict[str, Any] = async_result.get()
                results.append(result)

                if not args.verbose and not result["success"]:
                    logger.error(f"❌ {img.name}: {result['message']}")
                elif not args.verbose and result["success"]:
                    progress: str = f"[{processed}/{len(image_files)}]"
                    print(f"  {progress} ✅ {img.name}")

            except Exception as e:
                logger.error(f"❌ {img.name}: Unexpected error: {e!s}")
                results.append(
                    {
                        "path": img,
                        "success": False,
                        "original_size": 0,
                        "new_size": 0,
                        "message": f"Unexpected error: {e!s}",
                        "backup_created": False,
                    }
                )

    print("-" * 40)

    successful: int = sum(1 for r in results if r["success"])
    failed: int = len(results) - successful
    total_original: int = sum(r["original_size"] for r in results)
    total_new: int = sum(r["new_size"] for r in results)
    total_change: int = total_new - total_original

    print("📊 Summary:")
    print(f"   Total files: {len(results)}")
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📦 Original size: {fsz(total_original)}")
    print(f"   📦 New size: {fsz(total_new)}")
    if total_original > 0:
        print(
            f"   💰 Change: {fsz(total_change)} "
            f"({total_change / total_original * 100:+.1f}%)"
        )
    else:
        print(f"   💰 Change: {fsz(total_change)} (N/A)")

    if not args.no_size_report and len(dirs) > 0:
        print("📁 Folder size changes:")
        for dir_path in sorted(dirs):
            final_size: int = gsz(dir_path)
            initial_size: int = initial_sizes.get(dir_path, 0)
            change: int = final_size - initial_size
            if change != 0:
                percent: float = (
                    change / initial_size * 100 if initial_size > 0 else 0.0
                )
                print(f"   {dir_path}:")
                print(
                    f"      {fsz(initial_size)} → {fsz(final_size)} ({percent:+.1f}%)"
                )

    backups: list[dict[str, Any]] = [
        r for r in results if r.get("backup_created", False)
    ]
    if backups:
        print(f"💾 Backups created for {len(backups)} file(s)")
        if args.verbose:
            for r in backups[:5]:
                backup_path: Path = r["path"].with_suffix(r["path"].suffix + ".backup")
                print(f"   📋 {backup_path.name}")
            if len(backups) > 5:
                print(f"   ... and {len(backups) - 5} more")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
