#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def compress_folder(folder_path: Path, output_path: Path) -> bool:
    try:
        shutil.make_archive(str(folder_path), str(output_path), format="tar")
        return True
    except Exception:
        return False


def safe_remove(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
            print(f"Removed file: {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            print(f"Removed directory: {path}")
    except Exception as e:
        print(f"Error removing '{path}': {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tar_folder.py <folder_path>")
        sys.exit(1)
    folder_to_compress = Path(sys.argv[1])
    if not folder_to_compress.exists():
        print(f"Error: Folder '{folder_to_compress}' not found.")
        sys.exit(1)
    if not folder_to_compress.is_dir():
        print(f"Error: '{folder_to_compress}' is not a directory.")
        sys.exit(1)
    output_tar_path = folder_to_compress.parent / f"{folder_to_compress.name}.tar"
    if compress_folder(folder_to_compress, output_tar_path):
        safe_remove(folder_to_compress)
