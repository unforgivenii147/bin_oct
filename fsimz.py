#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys
from collections import defaultdict

from dh import get_files
from ppdeep import hash_from_file


def find_dups(cwd: str):
    files_by_hash = defaultdict(list)
    duplicate_count = 0
    deleted_count = 0
    total_deleted_size = 0
    files = get_files(cwd)
    for path in files:
        if path.is_symlink():
            continue
        if path.is_file():
            try:
                file_hash = hash_from_file(str(path))
                files_by_hash[file_hash].append(path)
            except Exception as e:
                print(f"Error processing file {path}: {e}")
                continue
    for file_hash, paths in files_by_hash.items():
        if len(paths) > 1:
            duplicate_count += len(paths) - 1
            paths.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for dup_found in paths:
                print(os.path.relpath(dup_found))
            for filetodel in paths[1:]:
                try:
                    get_size = filetodel.stat().st_size
                    deleted_count += 1
                    total_deleted_size += get_size
                except Exception as e:
                    print(f"Error deleting file {filetodel}: {e}")
        else:
            continue
    return (duplicate_count, deleted_count, total_deleted_size)


if __name__ == "__main__":
    root_folder = sys.argv[1].strip()
    find_dups(root_folder)
