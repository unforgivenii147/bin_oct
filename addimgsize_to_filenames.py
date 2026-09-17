#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import cv2
from tqdm import tqdm


class ImageDimensionRenamer:
    def __init__(self, root_dir: str = ".", separator: str = "_"):
        self.root_dir = Path(root_dir)
        self.separator = separator
        self.supported_formats = {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".gif",
            ".webp",
        }
        print("-" * 40)
        print("IMAGE DIMENSION RENAMER")
        print("-" * 40)
        print(f"[INIT] Root directory: {self.root_dir.resolve()}")
        print(f"[INIT] Separator: '{separator}'")
        print(f"[INIT] CPU cores available: {cpu_count()}")

    def get_all_images(self) -> list:
        print("\n[SCAN] Scanning for image files...")
        image_files = []
        for fmt in self.supported_formats:
            image_files.extend(self.root_dir.rglob(f"*{fmt}"))
            image_files.extend(self.root_dir.rglob(f"*{fmt.upper()}"))
        image_files = list(set(image_files))
        image_files = sorted(image_files)
        print(f"[SCAN] Found {len(image_files)} image file(s)")
        if image_files:
            print("[SCAN] Sample paths:")
            for img_path in image_files[:3]:
                print(f"       - {img_path.relative_to(self.root_dir)}")
            if len(image_files) > 3:
                print(f"       ... and {len(image_files) - 3} more")
        return image_files

    @staticmethod
    def has_dimensions_in_name(filename: str) -> bool:
        import re

        pattern = "\\d+[xX]\\d+"
        return bool(re.search(pattern, filename))

    def rename_image(self, args: tuple[Path, str, str]) -> tuple[Path, bool, str]:
        image_path, separator, root_dir_str = args
        root_dir = Path(root_dir_str)
        try:
            img = cv2.imread(str(image_path))
            if img is None:
                return image_path, False, "Failed to read image"
            height, width = img.shape[:2]
            dimensions = f"{width}x{height}"
            if self.has_dimensions_in_name(image_path.stem):
                message = "Already has dimensions in name"
                return image_path, False, message
            stem = image_path.stem
            suffix = image_path.suffix
            new_filename = f"{stem}{separator}{dimensions}{suffix}"
            new_path = image_path.parent / new_filename
            if new_path.exists() and new_path != image_path:
                return (
                    image_path,
                    False,
                    f"Target filename already exists: {new_filename}",
                )
            image_path.rename(new_path)
            rel_old = image_path.relative_to(root_dir)
            rel_new = new_path.relative_to(root_dir)
            message = f"{rel_old.name} → {rel_new.name} ({dimensions})"
            return new_path, True, message
        except Exception as e:
            return image_path, False, f"Error: {e!s}"

    def process_images(self, image_paths: list) -> None:
        if not image_paths:
            print("[WARN] No images to process!")
            return
        print(
            f"\n[PROCESS] Renaming {len(image_paths)} image(s) with {cpu_count()} process(es)..."
        )
        root_dir_str = str(self.root_dir.resolve())
        args_list = [
            (img_path, self.separator, root_dir_str) for img_path in image_paths
        ]
        successful = 0
        failed = 0
        already_processed = 0
        with Pool(processes=cpu_count()) as pool:
            results = list(
                tqdm(
                    pool.imap_unordered(self.rename_image, args_list),
                    total=len(image_paths),
                    desc="Processing",
                    unit="img",
                    ncols=80,
                )
            )
        print("\n[RESULTS]")
        print("-" * 40)
        for image_path, success, message in results:
            if success:
                successful += 1
                status = "✓ OK"
            elif "Already has dimensions" in message:
                already_processed += 1
                status = "⊘ SKIP"
            else:
                failed += 1
                status = "✗ FAIL"
            try:
                rel_path = image_path.relative_to(self.root_dir)
                path_str = str(rel_path)
            except ValueError:
                path_str = str(image_path)
            print(f"{status}  {path_str:<50} {message}")
        print("-" * 40)
        print(
            f"[SUMMARY] Renamed: {successful} | Skipped: {already_processed} | Failed: {
                failed
            } | Total: {len(image_paths)}"
        )

    def run(self) -> None:
        image_paths = self.get_all_images()
        if not image_paths:
            print("\n[WARN] No images found in directory!")
            return
        self.process_images(image_paths)
        print("\n" + "=" * 40)
        print("PROCESS COMPLETE - Images renamed with dimensions")
        print("-" * 40)


def main():
    separator = "_"
    if len(sys.argv) > 1:
        separator = sys.argv[1]
        if len(separator) > 1:
            print(
                f"[WARN] Separator should be single character, using first character: '{separator[0]}'"
            )
            separator = separator[0]
    renamer = ImageDimensionRenamer(root_dir=".", separator=separator)
    renamer.run()


if __name__ == "__main__":
    raise SystemExit(main())
