#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import cv2
from tqdm import tqdm


class ImageDownscaler:
    def __init__(self, root_dir: str = ".", scale_factor: float = 0.5):
        self.root_dir = Path(root_dir)
        self.scale_factor = scale_factor
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
        print("IMAGE DOWNSCALER")
        print("-" * 40)
        print(f"[INIT] Root directory: {self.root_dir.resolve()}")
        print(
            f"[INIT] Scale factor: {scale_factor} (new size = original × {scale_factor})"
        )
        print(f"[INIT] CPU cores available: {cpu_count()}")
        if not 0 < scale_factor <= 1.0:
            raise ValueError(
                "Scale factor must be between 0 (exclusive) and 1.0 (inclusive)"
            )
        if scale_factor == 1.0:
            print("[WARN] Scale factor is 1.0 - no downscaling will occur")

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
    def downscale_image(args: tuple[Path, float]) -> tuple[Path, bool, str]:
        image_path, scale_factor = args
        try:
            img = cv2.imread(str(image_path))
            if img is None:
                return image_path, False, "Failed to read image"
            height, width = img.shape[:2]
            original_size = width, height
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            new_size = new_width, new_height
            if new_width < 1 or new_height < 1:
                return image_path, False, f"New size too small ({new_size})"
            downscaled = cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)
            success = cv2.imwrite(str(image_path), downscaled)
            if not success:
                return image_path, False, "Failed to write image"
            message = f"{original_size} → {new_size}"
            return image_path, True, message
        except Exception as e:
            return image_path, False, f"Error: {e!s}"

    def process_images(self, image_paths: list) -> None:
        if not image_paths:
            print("[WARN] No images to process!")
            return
        print(f"""
[PROCESS] Downscaling {len(image_paths)} image(s) with {cpu_count()} process(es)...""")
        args_list = [(img_path, self.scale_factor) for img_path in image_paths]
        successful = 0
        failed = 0
        with Pool(processes=cpu_count()) as pool:
            results = list(
                tqdm(
                    pool.imap_unordered(self.downscale_image, args_list),
                    total=len(image_paths),
                    desc="Downscaling",
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
                rel_path = str(image_path.relative_to(self.root_dir))
                print(f"{status}  {rel_path:<50} {message}")
            else:
                failed += 1
                status = "✗ FAIL"
                rel_path = image_path.relative_to(self.root_dir)
                print(f"{status}  {rel_path:<50} {message}")
        print("-" * 40)
        print(
            f"[SUMMARY] Successful: {successful} | Failed: {failed} | Total: {len(image_paths)}"
        )

    def run(self) -> None:
        image_paths = self.get_all_images()
        if not image_paths:
            print("\n[WARN] No images found in directory!")
            return
        self.process_images(image_paths)
        print("\n" + "=" * 40)
        print("PROCESS COMPLETE - Images updated in-place")
        print("-" * 40)


def main():
    scale_factor = 0.5
    if len(sys.argv) > 1:
        try:
            scale_factor = float(sys.argv[1])
        except ValueError:
            print(f"[ERROR] Invalid scale factor: '{sys.argv[1]}'")
            print("Usage: python script.py [scale_factor]")
            print("Example: python script.py 0.5")
            sys.exit(1)
    downscaler = ImageDownscaler(root_dir=".", scale_factor=scale_factor)
    downscaler.run()


if __name__ == "__main__":
    raise SystemExit(main())
