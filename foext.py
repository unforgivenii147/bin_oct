#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

BASE_DIR = Path.cwd()
for item in BASE_DIR.iterdir():
    if not item.is_file():
        continue
    ext = item.suffix.lower().lstrip(".") or "no_extension"
    target_dir = BASE_DIR / ext
    target_dir.mkdir(exist_ok=True)
    shutil.move(str(item), target_dir / item.name)
