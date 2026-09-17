#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from imutils import paths


def dhash(image, hashSize=8) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hashSize + 1, hashSize))
    diff = resized[:, 1:] > resized[:, :-1]
    return sum(2**i for i, v in enumerate(diff.flatten()) if v)


def compute_hashes(dataset_path, hashSize=8):
    hashes = {}
    imagePaths = list(paths.list_images(dataset_path))
    for imagePath in imagePaths:
        image = cv2.imread(imagePath)
        if image is None:
            print(f"[WARN] unable to read image: {imagePath}")
            continue
        try:
            h = dhash(image, hashSize=hashSize)
        except Exception as e:
            print(f"[WARN] failed to hash {imagePath}: {e}")
            continue
        hashes.setdefault(h, []).append(imagePath)
    return hashes


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="imgdedup",
        description="Find and remove visually duplicate images using perceptual hashing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  imgdedup ./photos
  imgdedup ./photos --remove
        """,
    )
    ap.add_argument("path", help="path to image directory to scan")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="preview duplicates without deleting (default: True)",
    )
    ap.add_argument(
        "--remove", action="store_true", help="actually delete duplicate images"
    )
    args = vars(ap.parse_args())
    dataset_path = args["path"]
    if not Path(dataset_path).is_dir():
        raise SystemExit(msg)
    is_remove_mode = args["remove"]
    print("[INFO] computing image hashes...")
    hashes = compute_hashes(dataset_path)
    if not hashes:
        print("[INFO] no images found in directory")
        return
    print(f"[INFO] found {len(hashes)} unique image(s)")
    for h, hashedPaths in hashes.items():
        if len(hashedPaths) > 1:
            if not is_remove_mode:
                montage = None
                for p in hashedPaths:
                    image = cv2.imread(p)
                    if image is None:
                        print(f"[WARN] unable to read image for montage: {p}")
                        continue
                    image = cv2.resize(image, (900, 900))
                    montage = image if montage is None else np.hstack([montage, image])
                print(f"[INFO] found {len(hashedPaths) - 1} duplicates with hash: {h}")
            else:
                print(
                    f"[INFO] removing {len(hashedPaths) - 1} duplicates with hash: {h}"
                )
                for p in hashedPaths[1:]:
                    Path(p).unlink()


if __name__ == "__main__":
    raise SystemExit(main())
