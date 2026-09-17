#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from dh import get_files, mpf3, rrs, runcmd


def process_file(path) -> None:
    path = Path(path)
    if "lazy" in path.parts:
        return
    if not path.exists():
        return
    before = path.stat().st_size
    tmp_out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
        runcmd(["svgcleaner", str(path), str(tmp_out_path)], show_output=False)
        after = Path(tmp_out_path).stat().st_size
        if after:
            Path(tmp_out_path).replace(path)
            rrs(path, before, after)
            return
        return
    except Exception:
        return
    finally:
        if tmp_out_path and Path(tmp_out_path).exists():
            Path(tmp_out_path).unlink()


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".svg"])
    if not files:
        print("No SVG files found.")
        sys.exit(1)
    total_before = 0
    total_after = 0
    total_saved = 0
    results = mpf3(process_file, files)
