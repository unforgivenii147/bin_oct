#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from wheel.archive import wheel_load
from wheel.wheelfile import WheelFile

UNPACKED_WHEELS_SOURCE_DIR = Path.cwd()
WHEELS_OUTPUT_DIR = None


def find_dist_info_dir(pkg_dir: Path) -> Path | None:
    candidates = [
        p for p in pkg_dir.iterdir() if p.is_dir() and p.name.endswith(".dist-info")
    ]
    if not candidates:
        return None
    if len(candidates) > 1:
        print(
            f"Warning: Multiple .dist-info dirs found in {pkg_dir}, using the first: {candidates[0].name}",
            file=sys.stderr,
        )
    return candidates[0]


def create_wheel_for_dir(pkg_dir: Path, dest_dir: Path | None = None) -> None:
    dist_info = find_dist_info_dir(pkg_dir)
    if dist_info is None:
        print(f"Skipping {pkg_dir}: no *.dist-info dir found.")
        return
    try:
        metadata = wheel_load(dist_info)
        wheel_filename = metadata.WheelFilename
    except Exception as e:
        print(f"Error loading metadata from {dist_info}: {e}")
        print("Skipping this directory.")
        return
    output_path = dest_dir / wheel_filename if dest_dir else Path(wheel_filename)
    if dest_dir:
        dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Packing {pkg_dir} -> {output_path}")
    try:
        with WheelFile(str(output_path), "w", compression=zipfile.ZIP_DEFLATED) as wf:
            for item in pkg_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(pkg_dir).as_posix()
                    wf.write_to(str(item), arcname)
                elif item.is_dir() and item.name.endswith(".dist-info"):
                    pass
        print(f"Successfully created wheel: {output_path}")
    except Exception as e:
        print(f"Error creating wheel for {pkg_dir}: {e}")
        if output_path.exists():
            output_path.unlink()


def main() -> None:
    if WHEELS_OUTPUT_DIR:
        WHEELS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Output directory for wheels: {WHEELS_OUTPUT_DIR}")
    processed_count = 0
    for entry in UNPACKED_WHEELS_SOURCE_DIR.iterdir():
        if entry.is_dir() and not entry.name.endswith(".dist-info"):
            dist_info = find_dist_info_dir(entry)
            if dist_info:
                try:
                    create_wheel_for_dir(entry, dest_dir=WHEELS_OUTPUT_DIR)
                    processed_count += 1
                except Exception as e:
                    print(
                        f"Critical error while processing {entry}: {e}", file=sys.stderr
                    )
    print(f"\nDone. Processed {processed_count} directories.")


if __name__ == "__main__":
    try:
        pass
    except ImportError:
        print("Error: The 'wheel' library is not installed.")
        print("Please install it using: pip install wheel")
        sys.exit(1)
    raise SystemExit(main())
