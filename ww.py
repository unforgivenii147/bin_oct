#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

if __name__ == "__main__":
    target_dir = Path.cwd().resolve()
    os.chdir(target_dir.parent)
    subprocess.run(["wheel", "pack", str(target_dir), "-d", "/sdcard/whl"], check=False)
