#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path


def keep_one_image_per_folder(base_dir):
    base_path = Path(base_dir)
    image_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".webp",
        ".svg",
        ".heic",
        ".heif",
        ".raw",
    }
    group_folders = []
    for folder in base_path.iterdir():
        if folder.is_dir() and folder.name.startswith("similar_"):
            try:
                num_part = folder.name.split("_")[-1]
                int(num_part)
                group_folders.append(folder)
            except ValueError:
                print(f"Skipping {folder.name}: doesn't match expected pattern")
                continue
    print(f"Found {len(group_folders)} group folders")
    for folder in group_folders:
        print(f"\nProcessing: {folder.name}")
        image_files = []
        for file in folder.iterdir():
            if file.is_file() and file.suffix.lower() in image_extensions:
                image_files.append(file)
        if len(image_files) == 0:
            print(f"  No images found in {folder.name}")
            continue
        if len(image_files) == 1:
            print(f"  Already has only 1 image: {image_files[0].name}")
            continue
        keep_file = image_files[0]
        print(f"  Keeping: {keep_file.name}")
        for file in image_files[1:]:
            try:
                file.unlink()
                print(f"  Deleted: {file.name}")
            except Exception as e:
                print(f"  Error deleting {file.name}: {e}")
        print(f"  Done! {len(os.listdir(folder))} files remaining in folder")
    print(f"\n✅ Completed! Processed {len(group_folders)} folders.")


if __name__ == "__main__":
    base_directory = Path.cwd()
    if not os.path.exists(base_directory):
        print(f"Error: Directory '{base_directory}' not found!")
        print("Please update the 'base_directory' variable with the correct path.")
    else:
        print(f"⚠️  WARNING: This will delete images from folders in: {base_directory}")
        print("Only ONE image will be kept per folder. This action cannot be undone!")
        response = input("Do you want to continue? (yes/no): ").strip().lower()
        if response == "yes" or response == "y":
            keep_one_image_per_folder(base_directory)
        else:
            print("Operation cancelled.")
