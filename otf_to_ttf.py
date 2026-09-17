#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from pathlib import Path

try:
    import fontforge
except ImportError:
    print("This script must be run with FontForge's Python interpreter:")
    print("  fontforge -script otf2ttf_fontforge.py")
    sys.exit(1)


def convert_otf_to_ttf(otf_path):
    ttf_path = otf_path.with_suffix(".ttf")
    if ttf_path.exists():
        return "skipped", str(ttf_path)
    try:
        font = fontforge.open(str(otf_path))
        font.generate(str(ttf_path), flags=("opentype",))
        font.close()
        otf_path.unlink()
        return "success", str(ttf_path)
    except Exception as e:
        return "error", str(e)


def main():
    root_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(f"Searching for OTF files in: {root_dir}")
    otf_files = list(root_dir.rglob("*.otf"))
    if not otf_files:
        print("No OTF files found.")
        return
    print(f"Found {len(otf_files)} OTF file(s)\n")
    stats = {"success": 0, "skipped": 0, "error": 0}
    for otf_path in otf_files:
        print(f"Processing: {otf_path}")
        status, message = convert_otf_to_ttf(otf_path)
        if status == "success":
            print(f"  ✓ Converted: {message} (original removed)")
            stats["success"] += 1
        elif status == "skipped":
            print(f"  ⚠ Skipped: {message} (already exists)")
            stats["skipped"] += 1
        else:
            print(f"  ✗ Failed: {message}")
            stats["error"] += 1
    print(f"\n{'=' * 40}")
    print(
        f"Summary: {stats['success']} converted, {stats['skipped']} skipped, {stats['error']} failed"
    )


if __name__ == "__main__":
    raise SystemExit(main())
