#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from multiprocessing import Pool, cpu_count
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm


class ImageSimilarityOrganizer:
    def __init__(
        self, root_dir: str, similarity_threshold: float = 0.95, hash_size: int = 8
    ):
        self.root_dir = Path(root_dir)
        self.similarity_threshold = similarity_threshold
        self.hash_size = hash_size
        self.supported_formats = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif"}
        print(f"[INIT] Root directory: {self.root_dir}")
        print(f"[INIT] Similarity threshold: {similarity_threshold}")
        print(f"[INIT] Hash size: {hash_size}x{hash_size}")

    def get_all_images(self) -> list[Path]:
        print("\n[SCAN] Scanning for image files...")
        image_files = []
        for fmt in self.supported_formats:
            image_files.extend(self.root_dir.rglob(f"*{fmt}"))
            image_files.extend(self.root_dir.rglob(f"*{fmt.upper()}"))
        image_files = list(set(image_files))
        print(f"[SCAN] Found {len(image_files)} image(s)")
        return sorted(image_files)

    @staticmethod
    def compute_perceptual_hash(
        image_path: Path, hash_size: int = 8
    ) -> tuple[Path, np.ndarray]:
        try:
            img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                return image_path, None
            img_resized = cv2.resize(img, (hash_size, hash_size))
            avg = img_resized.mean()
            hash_array = (img_resized > avg).flatten().astype(int)
            return image_path, hash_array
        except Exception as e:
            print(f"[ERROR] Failed to hash {image_path}: {e!s}")
            return image_path, None

    def compute_hashes(self, image_paths: list[Path]) -> dict[Path, np.ndarray]:
        print(f"\n[HASH] Computing perceptual hashes using {cpu_count()} processes...")
        hashes = {}
        with Pool(processes=cpu_count()) as pool:
            from functools import partial

            compute_func = partial(
                self.compute_perceptual_hash, hash_size=self.hash_size
            )
            results = list(
                tqdm(
                    pool.imap_unordered(compute_func, image_paths),
                    total=len(image_paths),
                    desc="Hashing images",
                    unit="img",
                )
            )
        for image_path, hash_array in results:
            if hash_array is not None:
                hashes[image_path] = hash_array
        print(f"[HASH] Successfully hashed {len(hashes)} image(s)")
        return hashes

    @staticmethod
    def hamming_distance(hash1: np.ndarray, hash2: np.ndarray) -> int:
        return np.sum(hash1 != hash2)

    def find_similar_images(
        self, hashes: dict[Path, np.ndarray]
    ) -> dict[int, list[Path]]:
        print(
            f"\n[GROUP] Grouping similar images (threshold: {self.similarity_threshold})..."
        )
        image_list = list(hashes.keys())
        groups = {}
        group_id = 0
        assigned = set()
        max_distance = int((1 - self.similarity_threshold) * len(hashes[image_list[0]]))
        print(f"[GROUP] Max allowed hamming distance: {max_distance}")
        for i, img_path in enumerate(
            tqdm(image_list, desc="Grouping images", unit="img")
        ):
            if img_path in assigned:
                continue
            groups[group_id] = [img_path]
            assigned.add(img_path)
            for j, other_path in enumerate(image_list):
                if i >= j or other_path in assigned:
                    continue
                distance = self.hamming_distance(hashes[img_path], hashes[other_path])
                similarity = 1 - distance / len(hashes[img_path])
                if similarity >= self.similarity_threshold:
                    groups[group_id].append(other_path)
                    assigned.add(other_path)
            group_id += 1
        print(f"[GROUP] Created {len(groups)} group(s)")
        return groups

    def organize_images(self, groups: dict[int, list[Path]]) -> None:
        print("\n[ORGANIZE] Creating folders and organizing images...")
        for group_id, image_paths in tqdm(
            groups.items(), desc="Organizing", unit="group"
        ):
            if len(image_paths) == 1:
                continue
            group_folder = self.root_dir / f"similar_group_{group_id:04d}"
            group_folder.mkdir(exist_ok=True)
            for img_path in image_paths:
                try:
                    dest_path = group_folder / img_path.name
                    counter = 1
                    while dest_path.exists():
                        stem = img_path.stem
                        suffix = img_path.suffix
                        dest_path = group_folder / f"{stem}_{counter}{suffix}"
                        counter += 1
                    shutil.move(str(img_path), str(dest_path))
                except Exception as e:
                    print(f"[ERROR] Failed to move {img_path}: {e!s}")
        print(f"[ORGANIZE] Done! Check {self.root_dir} for organized groups")

    def run(self) -> None:
        print("-" * 40)
        print("IMAGE SIMILARITY ORGANIZER")
        print("-" * 40)
        image_paths = self.get_all_images()
        if not image_paths:
            print("[WARN] No images found!")
            return
        hashes = self.compute_hashes(image_paths)
        if not hashes:
            print("[ERROR] Could not hash any images!")
            return
        groups = self.find_similar_images(hashes)
        self.organize_images(groups)
        print("\n" + "=" * 40)
        print("PROCESS COMPLETE")
        print("-" * 40)


if __name__ == "__main__":
    ROOT_DIRECTORY = Path.cwd()
    SIMILARITY_THRESHOLD = 0.9
    organizer = ImageSimilarityOrganizer(
        root_dir=ROOT_DIRECTORY, similarity_threshold=SIMILARITY_THRESHOLD, hash_size=16
    )
    organizer.run()
