#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from pathlib import Path


def load_names(names_path):
    names = set()
    try:
        with Path(names_path).open("r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name:
                    parts = name.split()
                    if len(parts) >= 2:
                        first_initial_pattern = re.escape(parts[0][0].upper())
                        last_initial_pattern = re.escape(parts[-1][0].upper())
                        pattern_str = rf"{first_initial_pattern}[\\w\\s\\-r']+\s+{last_initial_pattern}[\w\s\-']+"
                        names.add((name, re.compile(pattern_str, re.IGNORECASE)))
                    else:
                        names.add(
                            (
                                name,
                                re.compile(
                                    re.escape(name[0].upper()) + "[\\w\\s\\-']+",
                                    re.IGNORECASE,
                                ),
                            )
                        )
    except FileNotFoundError:
        print(f"Error: Names file not found at {names_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading names file: {e}")
        sys.exit(1)
    return names


def find_names_in_files(names_db_path: str = "names.txt") -> None:
    names_to_find = load_names(names_db_path)
    if not names_to_find:
        return
    found_names = {}
    cwd = Path.cwd()
    for path in cwd.rglob("*"):
        if path.is_file() and path.suffix in {
            ".txt",
            ".md",
            ".log",
            ".py",
            ".html",
            ".css",
            ".js",
            ".json",
            ".xml",
            ".yml",
            ".yaml",
        }:
            try:
                with Path(path).open("r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    for original_name, pattern in names_to_find:
                        for match in pattern.finditer(content):
                            match.span()
                            matched_text = match.group(0)
                            match_parts = matched_text.strip().split()
                            if len(match_parts) >= 2 and (
                                match_parts[0][0].upper()
                                == original_name.split()[0][0].upper()
                                and match_parts[-1][0].upper()
                                == original_name.split()[-1][0].upper()
                            ):
                                if original_name not in found_names:
                                    found_names[original_name] = []
                                entry = {
                                    "file": str(path.relative_to(cwd)),
                                    "match": matched_text,
                                }
                                if entry not in found_names[original_name]:
                                    found_names[original_name].append(entry)
            except Exception as e:
                print(f"Could not read file {path}: {e}")
    if not found_names:
        print("No target names found in the specified files.")
        return
    print(f"Found names (from {names_db_path}):")
    for name, occurrences in found_names.items():
        print(f"\n- {name}:")
        for occ in occurrences:
            print(f"  - File: {occ['file']}, Match: '{occ['match']}'")


if __name__ == "__main__":
    names_database_path = "/sdcard/data/male_names"
    if len(sys.argv) > 1:
        names_database_path = sys.argv[1]
    find_names_in_files(names_database_path)
