#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import operator
from pathlib import Path

import ssdeep
from dh import get_files


def calculate_ssdeep_hash(path: Path, min_file_size: int = 1):
    try:
        if path.stat().st_size < min_file_size:
            return None
        with path.open("rb") as f:
            data = f.read()
            if len(data) < min_file_size:
                return None
            return ssdeep.hash(data)
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def compare_files(paths: list[Path], similarity_threshold: int = 70):
    file_hashes = {}
    for path in paths:
        file_hash = calculate_ssdeep_hash(path)
        if file_hash:
            file_hashes[str(path)] = file_hash
    similarities = []
    cwd = Path.cwd()
    paths_list = list(file_hashes.keys())
    for i in range(len(paths_list)):
        for j in range(i + 1, len(paths_list)):
            path1_str = paths_list[i]
            path2_str = paths_list[j]
            hash1 = file_hashes[path1_str]
            hash2 = file_hashes[path2_str]
            try:
                score = ssdeep.compare(hash1, hash2)
                if score >= similarity_threshold:
                    similarities.append(
                        {
                            "file1": str(Path(path1_str).relative_to(cwd)),
                            "file2": str(Path(path2_str).relative_to(cwd)),
                            "similarity_score": score,
                        }
                    )
            except ssdeep.error as e:
                print(f"Error comparing hashes for {path1_str} and {path2_str}: {e}")
            except Exception as e:
                print(
                    f"An unexpected error occurred during comparison for {path1_str} and {path2_str}: {e}"
                )
    similarities.sort(key=operator.itemgetter("similarity_score"), reverse=True)
    return similarities


def save_to_json(data, filename: str = "simz.json") -> None:
    try:
        with Path(filename).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving data to JSON file '{filename}': {e}")


if __name__ == "__main__":
    cwd = Path.cwd()
    MIN_SIMILARITY_THRESHOLD = 50
    OUTPUT_JSON_FILE = "simz.json"
    files = get_files(cwd)
    if not files:
        print("No files found matching the criteria in the specified directory.")
    else:
        similar_file_pairs = compare_files(files, MIN_SIMILARITY_THRESHOLD)
        if similar_file_pairs:
            save_to_json(similar_file_pairs, OUTPUT_JSON_FILE)
        else:
            print(f"\nNo files found with similarity >= {MIN_SIMILARITY_THRESHOLD}%.")
