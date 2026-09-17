#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import json
from pathlib import Path


def freeze_to_json(
    input_file: str = "pip.freeze", output_file: str = "packages.json"
) -> None:
    packages = {}
    with Path(input_file).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "==" in line:
                pkg, ver = line.split("==", 1)
                packages[pkg] = ver
    with Path(output_file).open("w", encoding="utf-8") as f:
        json.dump(packages, f, indent=4)
    print(f"Saved {len(packages)} packages to {output_file}")


if __name__ == "__main__":
    freeze_to_json()
