#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

import ssdeep

SEARCH_DIR = Path.cwd()
OUTPUT_DIR = SEARCH_DIR / "output"
SIMILARITY_THRESHOLD = 60
MIN_GROUP_SIZE = 2


def calculate_fuzzy_hash(path: Path) -> str:
    try:
        return ssdeep.hash_from_file(str(path))
    except ssdeep.Error as e:
        print(f"Error calculating ssdeep hash for {path}: {e}")
        return ""
    except Exception as e:
        print(f"Unexpected error for {path}: {e}")
        return ""


def find_similar_files(
    search_dir: Path, output_dir: Path, similarity_threshold: int, min_group_size: int
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_hashes: dict[Path, str] = {}
    for path in search_dir.rglob("*"):
        if path.is_file() and not path.is_symlink():
            hash_value = calculate_fuzzy_hash(path)
            if hash_value:
                file_hashes[path] = hash_value
    if not file_hashes:
        print("No files found or no hashes could be generated.")
        return
    similar_groups: dict[Path, list[Path]] = {}
    processed_files = set()
    paths = list(file_hashes.keys())
    num_files = len(paths)
    for i in range(num_files):
        current_file = paths[i]
        if current_file in processed_files:
            continue
        current_hash = file_hashes[current_file]
        current_group = [current_file]
        for j in range(i + 1, num_files):
            other_file = paths[j]
            if other_file in processed_files:
                continue
            other_hash = file_hashes[other_file]
            try:
                similarity = ssdeep.compare(current_hash, other_hash)
                if similarity >= similarity_threshold:
                    print(
                        f"  - Found similarity ({similarity}/{current_hash} vs {other_hash} -> {other_file})"
                    )
                    current_group.append(other_file)
            except ssdeep.Error as e:
                print(
                    f"Error comparing hashes for {current_file} and {other_file}: {e}"
                )
            except Exception as e:
                print(
                    f"Unexpected error comparing hashes for {current_file} and {other_file}: {e}"
                )
        if len(current_group) >= min_group_size:
            processed_files.update(current_group)
            representative_file = current_group[0]
            similar_groups[representative_file] = current_group
            print(
                f"  -> Added group (starting with {representative_file.name}) with {len(current_group)} files."
            )
    print("\n--- Moving Similar Files ---")
    moved_files_count = 0
    group_counter = 0
    files_to_move = set()
    final_groups_to_move = []
    for rep_file, group in similar_groups.items():
        valid_group = [f for f in group if f not in processed_files or f == rep_file]
        if len(valid_group) >= min_group_size:
            final_groups_to_move.append(valid_group)
            files_to_move.update(valid_group)
    processed_files.update(files_to_move)
    for group in final_groups_to_move:
        group_counter += 1
        group_output_subdir = output_dir / f"group_{group_counter:03d}"
        group_output_subdir.mkdir(parents=True, exist_ok=True)
        print(f"Creating group directory: {group_output_subdir}")
        for file_to_move in group:
            try:
                dest_path = group_output_subdir / file_to_move.name
                if dest_path.exists():
                    print(
                        f"  - Warning: Destination file already exists, skipping: {dest_path}"
                    )
                    continue
                shutil.move(str(file_to_move), str(dest_path))
                print(f"  - Moved: {file_to_move.name} to {group_output_subdir.name}/")
                moved_files_count += 1
            except FileNotFoundError:
                print(
                    f"  - Error: File not found during move (might have been moved already or deleted): {file_to_move}"
                )
            except Exception as e:
                print(f"  - Error moving {file_to_move.name}: {e}")
    print("\n--- Summary ---")
    if group_counter == 0:
        print("No groups of similar files found that met the criteria.")
    else:
        print(f"Moved {moved_files_count} files into {group_counter} groups.")
        print(f"Similar files have been moved to: {output_dir}")


if __name__ == "__main__":
    if Path.cwd() == SEARCH_DIR:
        print("INFO: Processing files in the current directory.")
    else:
        print(f"INFO: Processing files in: {SEARCH_DIR}")
    if SEARCH_DIR.resolve() == OUTPUT_DIR.resolve():
        print(
            "ERROR: SEARCH_DIR and OUTPUT_DIR cannot be the same. Please configure them differently."
        )
    else:
        find_similar_files(
            search_dir=SEARCH_DIR,
            output_dir=OUTPUT_DIR,
            similarity_threshold=SIMILARITY_THRESHOLD,
            min_group_size=MIN_GROUP_SIZE,
        )
