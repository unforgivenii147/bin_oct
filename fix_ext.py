#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

from dh import get_files

try:
    import puremagic
except ImportError:
    print("Error: This script requires the 'puremagic' library.")
    print("Please install it by running: pip install puremagic")
    sys.exit(1)


def get_extension_from_mime(mime_type: str) -> str:
    mime_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/x-tar": ".tar",
        "application/gzip": ".gz",
        "application/x-7z-compressed": ".7z",
        "application/x-rar": ".rar",
        "video/mp4": ".mp4",
        "video/x-msvideo": ".avi",
        "video/quicktime": ".mov",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "text/plain": ".txt",
        "application/octet-stream": "",
    }
    return mime_map.get(mime_type, "")


def detect_true_extension(path: Path) -> str:
    try:
        magic_data = puremagic.magic_string(path.read_bytes())
        if magic_data:
            best_match = magic_data[0]
            ext = best_match.extension
            if ext and ext != "":
                return ext if ext.startswith(".") else f".{ext}"
            mime_ext = get_extension_from_mime(best_match.mime_type)
            if mime_ext:
                return mime_ext
    except puremagic.main.PureError:
        pass
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return ""


def check_file(path: Path) -> tuple[Path, str, str] | None:
    current_ext = path.suffix.lower()
    if not current_ext:
        return None
    true_ext = detect_true_extension(path)
    if not true_ext:
        return None
    true_ext = true_ext.lower()
    if current_ext != true_ext:
        normalize_pairs = {".jpeg": ".jpg", ".htm": ".html", ".tif": ".tiff"}
        norm_current = normalize_pairs.get(current_ext, current_ext)
        norm_true = normalize_pairs.get(true_ext, true_ext)
        if norm_current != norm_true:
            return (path, current_ext, true_ext)
    return None


def autofix_filename(path: Path, current_ext: str, true_ext: str) -> Path:
    new_name = path.stem + true_ext
    new_path = path.with_name(new_name)
    counter = 1
    original_new_path = new_path
    while new_path.exists() and new_path != path:
        new_path = original_new_path.with_name(
            f"{original_new_path.stem}_{counter}{true_ext}"
        )
        counter += 1
    if new_path != path:
        path.rename(new_path)
        return new_path
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Recursively detect and optionally fix file extension mismatches based on file headers (magic numbers)."
    )
    parser.add_argument(
        "directory", type=str, help="The directory to recursively scan."
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically rename files to fix detected mismatches in place.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker threads (default: 4).",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory)
    if not root_dir.is_dir():
        print(f"Error: '{root_dir}' is not a valid directory.")
        sys.exit(1)
    print(f"Scanning '{root_dir}' for extension mismatches...")
    if args.autofix:
        print("Autofix is ENABLED. Files will be renamed.")
    cwd = Path.cwd()
    all_files = get_files(cwd)
    mismatches = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(check_file, f): f for f in all_files}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                mismatches.append(result)
    if not mismatches:
        print("No extension mismatches found!")
        return
    print(f"\nFound {len(mismatches)} mismatches:")
    for path, current_ext, true_ext in sorted(mismatches):
        print(
            f"[MISMATCH] '{path}' | Current: '{current_ext}' | Detected: '{true_ext}'"
        )
        if args.autofix:
            try:
                new_path = autofix_filename(path, current_ext, true_ext)
                if new_path != path:
                    print(f"  -> Fixed: Renamed to '{new_path.name}'")
                else:
                    print("  -> Skipped fix: Filename collision or identical.")
            except Exception as e:
                print(f"  -> Error fixing file: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
