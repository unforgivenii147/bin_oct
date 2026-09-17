#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path


def clean_requirements(fname: str) -> None:
    with Path(fname).open(encoding="utf-8") as f:
        lines = f.readlines()
    packages = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = line.split(">")[0].split("<")[0].split("=")[0].split("~")[0].strip()
        if pkg:
            packages.add(pkg)
    Path(fname).write_text("\n".join(sorted(packages)), encoding="utf-8")
    print(f"Updated  {fname} with {len(packages)} unique packages.")


if __name__ == "__main__":
    fn = sys.argv[1]
    clean_requirements(fn)
