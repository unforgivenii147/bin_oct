#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from email import policy
from email.parser import Parser
from pathlib import Path


def extract_wheel_metadata(wheel_path: Path) -> dict:
    with zipfile.ZipFile(wheel_path, "r") as wheel_zip:
        metadata_files = [
            f for f in wheel_zip.namelist() if f.endswith(".dist-info/METADATA")
        ]
        if not metadata_files:
            raise ValueError(f"No METADATA found in wheel {wheel_path}")
        metadata_content = wheel_zip.read(metadata_files[0]).decode("utf-8")
        metadata = Parser(policy=policy.compat32).parsestr(metadata_content)
    wheel_metadata = {
        "url": f"file://{wheel_path.absolute()}",
        "filename": wheel_path.name,
        "size": wheel_path.stat().st_size,
        "sha224": hashlib.sha224(wheel_path.read_bytes()).hexdigest(),
        "origin": "manual_cache",
    }
    metadata_fields = [
        "Name",
        "Version",
        "Summary",
        "Home-page",
        "Author",
        "License",
        "Requires-Python",
        "Requires-Dist",
    ]
    for field in metadata_fields:
        value = metadata.get(field)
        if value:
            wheel_metadata[field.lower().replace("-", "_")] = value
    return wheel_metadata


def add_wheel_to_pip_cache(wheel_path: Path):
    cache_dir = subprocess.check_output(["pip", "cache", "dir"]).decode().strip()
    wheels_cache = Path(cache_dir) / "wheels"
    wheel_data = wheel_path.read_bytes()
    hash1 = hashlib.sha224(wheel_data).hexdigest()
    target_dir = wheels_cache / hash1[:2] / hash1[2:4] / hash1
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / wheel_path.name
    shutil.copy2(wheel_path, target_file)
    metadata = extract_wheel_metadata(wheel_path)
    metadata_file = target_dir / f"{wheel_path.name}.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Wheel cached at: {target_file}")
    print(f"Metadata cached at: {metadata_file}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python add_wheel_to_cache.py <path/to/wheel.whl>")
        sys.exit(1)
    wheel_file = Path(sys.argv[1])
    if not wheel_file.exists():
        print(f"Error: Wheel file {wheel_file} does not exist")
        sys.exit(1)
    add_wheel_to_pip_cache(wheel_file)
