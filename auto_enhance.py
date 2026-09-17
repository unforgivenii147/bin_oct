#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def enhance_image(
    image_path: Path, verbose: bool = False, progress: tuple | None = None
) -> bool:
    try:
        if progress:
            current, total = progress
            print(f"[{current}/{total}] {image_path.name}")
        elif verbose:
            print(f"[PROCESSING] {image_path.name}...")
        img = cv2.imread(str(image_path))
        if img is None:
            print(f"[ERROR] Could not read: {image_path}")
            return False
        denoised = cv2.fastNlMeansDenoisingColored(img, None, 3, 3, 7, 21)
        del img
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        del denoised
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l_channel)
        enhanced_lab = cv2.merge((cl, a_channel, b_channel))
        del lab, l_channel, a_channel, b_channel, cl
        color_corrected = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        del enhanced_lab
        hsv = cv2.cvtColor(color_corrected, cv2.COLOR_BGR2HSV)
        del color_corrected
        h, s, v = cv2.split(hsv)
        s = np.clip(s * 1.1, 0, 255).astype(np.uint8)
        enhanced_hsv = cv2.merge((h, s, v))
        del hsv, h, s, v
        vibrant_img = cv2.cvtColor(enhanced_hsv, cv2.COLOR_HSV2BGR)
        del enhanced_hsv
        gaussian_blur = cv2.GaussianBlur(vibrant_img, (0, 0), 2.0)
        final_enhanced = cv2.addWeighted(vibrant_img, 1.5, gaussian_blur, -0.5, 0)
        del vibrant_img, gaussian_blur
        cv2.imwrite(str(image_path), final_enhanced)
        del final_enhanced
        if verbose and not progress:
            print(f"[SUCCESS] Enhanced and replaced: {image_path.name}")
        return True
    except Exception as e:
        print(f"[FAILED] Error processing {image_path.name}: {e}")
        return False


def collect_images(input_paths) -> list:
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    images_to_process = []
    if not input_paths:
        print(
            "[INFO] No inputs provided. Scanning current directory '.' recursively..."
        )
        input_paths = [Path(".")]
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file() and path.suffix.lower() in valid_extensions:
            images_to_process.append(path)
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file() and file.suffix.lower() in valid_extensions:
                    images_to_process.append(file)
        else:
            print(f"[WARNING] Skipping invalid path or unsupported format: {path_str}")
    return list(set(images_to_process))


def process_sequential(tasks, verbose):
    results = []
    for i, (img, _) in enumerate(tasks, 1):
        result = enhance_image(img, verbose, (i, len(tasks)))
        results.append(result)
    return results


def process_parallel(tasks, num_cores):
    import multiprocessing as mp

    total = len(tasks)
    print(f"[SYSTEM] Utilizing {num_cores} parallel CPU threads.")
    parallel_tasks = []
    for i, (img, _verbose) in enumerate(tasks, 1):
        print(f"[{i}/{total}] {img.name}")
        parallel_tasks.append((img, False))
    with mp.Pool(processes=num_cores) as pool:
        results = pool.starmap(enhance_image, parallel_tasks)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Google Photos Style Auto-Enhancer (In-place replacement)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Files or folders to process. Defaults to recursive '.' if empty.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print details for every image processed.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable multiprocessing (sequential is default).",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel jobs. Default is CPU count.",
    )
    args = parser.parse_args()
    image_pool = collect_images(args.inputs)
    total_images = len(image_pool)
    if total_images == 0:
        print("[INFO] No supported images found to enhance. Exiting.")
        sys.exit(0)
    print(f"\n[START] Found {total_images} target images.")
    print("[WARNING] Images will be ENHANCED IN-PLACE (originals will be overwritten)!")
    tasks = [(img, args.verbose) for img in image_pool]
    if args.parallel:
        try:
            import multiprocessing as mp

            num_cores = args.jobs if args.jobs else mp.cpu_count()
            results = process_parallel(tasks, num_cores)
        except ImportError:
            print(
                "[WARNING] multiprocessing not available. Falling back to sequential."
            )
            results = process_sequential(tasks, args.verbose)
    else:
        print("[SYSTEM] Processing sequentially (default mode)...")
        results = process_sequential(tasks, args.verbose)
    successful_runs = sum(1 for r in results if r)
    print("[FINISHED] Done")


if __name__ == "__main__":
    raise SystemExit(main())
