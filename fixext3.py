#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
from pathlib import Path

FILE_TYPE_MAP = {
    "xz compressed data": ".xz",
    "jpeg image data": ".jpg",
    "png image data": ".png",
    "gif image data": ".gif",
    "tiff image data": ".tiff",
    "bitmap image data": ".bmp",
    "svg image data": ".svg",
    "pdf document": ".pdf",
    "microsoft word document": ".doc",
    "microsoft office document": ".docx",
    "excel spreadsheet": ".xls",
    "microsoft excel (openxml) spreadsheet": ".xlsx",
    "powerpoint presentation": ".ppt",
    "microsoft powerpoint (openxml) presentation": ".pptx",
    "zip archive data": ".zip",
    "gzip compressed data": ".gz",
    "tar archive data": ".tar",
    "bzip2 compressed data": ".bz2",
    "gzip compressed data, from Unix, original size": ".gz",
    "shared object (linux)": ".so",
    "python script": ".py",
    "javascript (ECMAScript)": ".js",
    "html document": ".html",
    "xml document": ".xml",
    "json data": ".json",
    "c source, ascii text": ".c",
    "c++ source, ascii text": ".cpp",
    "assembly language, ascii text": ".s",
    "makefile": ".mk",
    "ascii text": ".txt",
    "utf-8 unicode text": ".txt",
    "iso-8859 text": ".txt",
    "data": ".bin",
    "java class file": ".class",
    "executable file": ".exe",
    "elf 64-bit lsb executable": ".elf",
    "mach-o executable": ".dylib",
    "png image,": ".png",
    "jpeg image,": ".jpg",
    "mpeg sequence": ".mpeg",
    "mpeg adts,": ".aac",
    "midi": ".mid",
    "wave sound data": ".wav",
    "mpeg audio": ".mp3",
    "java serialized data": ".ser",
    "pkcs#7": ".p7",
}
EXTENSION_TO_TYPE_HINT = {
    ".xz": ["xz compressed data"],
    ".jpg": ["jpeg image data"],
    ".png": ["png image data"],
    ".gif": ["gif image data"],
    ".pdf": ["pdf document"],
    ".doc": ["microsoft word document"],
    ".docx": ["microsoft office document"],
    ".xls": ["excel spreadsheet"],
    ".xlsx": ["microsoft excel (openxml) spreadsheet"],
    ".ppt": ["powerpoint presentation"],
    ".pptx": ["microsoft powerpoint (openxml) presentation"],
    ".zip": ["zip archive data"],
    ".gz": ["gzip compressed data"],
    ".tar": ["tar archive data"],
    ".bz2": ["bzip2 compressed data"],
    ".py": ["python script"],
    ".js": ["javascript (ecmascript)"],
    ".html": ["html document"],
    ".xml": ["xml document"],
    ".json": ["json data"],
    ".c": ["c source"],
    ".cpp": ["c++ source"],
    ".txt": ["ascii text", "utf-8 unicode text", "iso-8859 text"],
    ".exe": ["executable file"],
    ".elf": ["elf 64-bit lsb executable"],
    ".dylib": ["mach-o executable"],
    ".mp3": ["mpeg audio"],
    ".wav": ["wave sound data"],
    ".mp4": ["mpeg sequence"],
    ".mov": ["quicktime movie"],
    ".avi": ["avi video"],
}


def run_file_command(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["file", "-b", str(path)],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()
    except FileNotFoundError:
        print(
            "Error: 'file' command not found. Please ensure it's installed and in your PATH."
        )
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error running 'file' command on {path}: {e}")
        return None
    except Exception as e:
        print(
            f"An unexpected error occurred while running 'file' command on {path}: {e}"
        )
        return None


def get_file_extension_from_type(file_type_description: str) -> str | None:
    normalized_description = file_type_description.lower().strip()
    if normalized_description.endswith(","):
        normalized_description = normalized_description[:-1].strip()
    if normalized_description.endswith("."):
        normalized_description = normalized_description[:-1].strip()
    return FILE_TYPE_MAP.get(normalized_description)


def get_current_extension(path: Path) -> str | None:
    return path.suffix.lower()


def find_files_recursively(
    directory: Path,
    ignored_dirs: list[str] | None = None,
    follow_symlinks: bool = False,
):
    if ignored_dirs is None:
        ignored_dirs = [".git", "__pycache__", "node_modules", ".venv", "venv"]
    for item in directory.rglob("*"):
        if item.is_dir() and any(
            ignored_dir == item.name for ignored_dir in ignored_dirs
        ):
            continue
        if item.is_symlink() and not follow_symlinks:
            continue
        if item.is_file():
            yield item


def detect_and_fix_mismatches(
    start_directory: Path = Path(), similarity_threshold: int = 70, dry_run: bool = True
) -> None:
    print("--- Starting File Type Mismatch Detection ---")
    print(f"Scanning directory: {start_directory.resolve()}")
    if dry_run:
        print("--- Running in DRY-RUN mode. No files will be renamed. ---")
    else:
        print(
            "--- WARNING: Running in LIVE mode. Files WILL be renamed. Ensure you have backups! ---"
        )
    mismatched_files_found = []
    rename_operations = []
    files_to_process = list(find_files_recursively(start_directory))
    print(f"Found {len(files_to_process)} files to analyze.")
    for path in files_to_process:
        current_ext = get_current_extension(path)
        if not current_ext or current_ext in {".log", ".tmp", ".bak"}:
            continue
        file_type_desc = run_file_command(path)
        if not file_type_desc:
            continue
        detected_ext = get_file_extension_from_type(file_type_desc)
        is_generic_text = any(
            text_type in file_type_desc.lower()
            for text_type in [
                "ascii text",
                "utf-8 unicode text",
                "iso-8859 text",
                "plain text",
            ]
        )
        if is_generic_text and current_ext in {
            ".txt",
            ".log",
            ".csv",
            ".md",
            ".ini",
            ".cfg",
            ".yml",
            ".yaml",
        }:
            continue
        if not detected_ext:
            continue
        if detected_ext.lower() != current_ext.lower():
            mismatched_files_found.append(
                {
                    "path": path,
                    "current_extension": current_ext,
                    "detected_type": file_type_desc,
                    "detected_extension": detected_ext,
                }
            )
            new_path = path.with_suffix(detected_ext)
            if new_path.exists():
                print(
                    f"  SKIP RENAME: Target file '{new_path}' already exists. Cannot rename '{path}'."
                )
            else:
                rename_operations.append(
                    {
                        "source": path,
                        "destination": new_path,
                        "type_description": file_type_desc,
                    }
                )
                print(
                    f"  MISMATCH FOUND: '{path}' detected as '{
                        file_type_desc
                    }' (suggested extension: {detected_ext})."
                )
    print("\n--- Analysis Complete ---")
    if not mismatched_files_found:
        print("No file extension mismatches detected.")
        return
    print(
        f"Found {len(mismatched_files_found)} files with potential extension mismatches."
    )
    if not rename_operations:
        print(
            "No safe rename operations could be planned (e.g., due to existing files or no clear extension mapping)."
        )
        return
    print(f"\nIdentified {len(rename_operations)} files that can be safely renamed:")
    for op in rename_operations:
        print(
            f"  - '{op['source']}' -> '{op['destination']}' (Detected as: {op['type_description']})"
        )
    if dry_run:
        print("\n--- DRY-RUN MODE ACTIVE ---")
        print(
            "No files were renamed. To perform renames, set 'dry_run=False' in the script."
        )
    else:
        print("\n--- LIVE RENAME MODE ACTIVE ---")
        confirm = input(
            "Are you sure you want to proceed with renaming these files? (yes/no): "
        )
        if confirm.lower() == "yes":
            renamed_count = 0
            for op in rename_operations:
                try:
                    op["source"].rename(op["destination"])
                    print(f"  Renamed '{op['source']}' to '{op['destination']}'")
                    renamed_count += 1
                except OSError as e:
                    print(
                        f"  ERROR renaming '{op['source']}' to '{op['destination']}': {e}"
                    )
                except Exception as e:
                    print(
                        f"  UNEXPECTED ERROR renaming '{op['source']}' to '{op['destination']}': {e}"
                    )
            print(f"""
Successfully renamed {renamed_count} out of {len(rename_operations)} planned operations.""")
        else:
            print("Rename operation cancelled by user.")
    print("\n--- Script Finished ---")


if __name__ == "__main__":
    TARGET_DIR = Path()
    DRY_RUN_MODE = False
    detect_and_fix_mismatches(start_directory=TARGET_DIR, dry_run=DRY_RUN_MODE)
