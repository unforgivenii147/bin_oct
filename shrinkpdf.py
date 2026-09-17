#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

from dh import fsz, runcmd


def process_file(path: Path) -> None:
    path = Path(path)
    temp_gs = path.with_name(f"temp_gs_{path.name}")
    size_before = path.stat().st_size
    print(f"Before : {fsz(size_before)}")
    gs_cmd = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        "-dColorImageResolution=65",
        "-dGrayImageResolution=65",
        "-dMonoImageResolution=65",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dMonoImageDownsampleType=/Subsample",
        "-dNOPAUSE",
        "-dBATCH",
        f"-sOutputFile={temp_gs}",
        str(path),
    ]
    runcmd(gs_cmd, show_output=False)
    if temp_gs.exists():
        size_after = temp_gs.stat().st_size
        if size_after:
            print(f"After  : {fsz(size_after)}")
            diff = size_before - size_after
            sign = "-" if diff >= 0 else "+"
            if size_after < size_before:
                temp_gs.replace(path)
                print(f"Saved  : {sign}{fsz(diff)}")
            else:
                print("original file is smaller")
                temp_gs.unlink(missing_ok=True)


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        files = [Path(p) for p in args]
        for path in files:
            process_file(path)
        sys.exit(0)
    for path in cwd.rglob("*.pdf"):
        process_file(path)


if __name__ == "__main__":
    raise SystemExit(main())
