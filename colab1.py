#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
import site
import zipfile
from pathlib import Path

from google.colab import drive

drive.mount("/content/drive")
site_pkgs = Path(site.getsitepackages()[0])
out_dir = Path("/content/drive/MyDrive/wheels")
out_dir.mkdir(parents=True, exist_ok=True)
EXCLUDE_PREFIXES = "setuptools", "pip"


def excluded(name: str) -> bool:
    return name.startswith(EXCLUDE_PREFIXES)


copied_files = 0
zipped_dirs = 0
for entry in site_pkgs.iterdir():
    name = entry.name
    if excluded(name):
        continue
    if entry.is_file():
        shutil.copy2(entry, out_dir / name)
        copied_files += 1
    elif entry.is_dir():
        zip_path = out_dir / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in entry.rglob("*"):
                if path.is_file() and path.suffix != ".pyc":
                    zf.write(path, path.relative_to(site_pkgs))
        zipped_dirs += 1
print("Export completed successfully.")
print(f"Site-packages source : {site_pkgs}")
print(f"Output directory     : {out_dir}")
print(f"Top-level files copied : {copied_files}")
print(f"Top-level dirs zipped  : {zipped_dirs}")
print("Excluded packages     : torch, tensorflow")
