#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
import os
from pathlib import Path


def rename_pypi_metadata_files() -> None:
    files = [f for f in os.listdir(".") if f.endswith(".json")]
    for filename in files:
        try:
            with Path(filename).open(encoding="utf-8") as f:
                data = json.load(f)
            pkg_name = None
            if "info" in data and "name" in data["info"]:
                pkg_name = data["info"]["name"]
            elif "name" in data:
                pkg_name = data["name"]
            if pkg_name:
                new_name = f"{pkg_name}.json"
                if filename == new_name:
                    print(f"Skipping: {filename} is already correctly named.")
                    continue
                Path(filename).rename(new_name)
                print(f"Renamed: {filename} -> {new_name}")
            else:
                print(f"Warning: Could not find package name in {filename}")
        except json.JSONDecodeError:
            print(f"Error: {filename} is not a valid JSON file.")
        except Exception as e:
            print(f"An error occurred with {filename}: {e}")


if __name__ == "__main__":
    rename_pypi_metadata_files()
