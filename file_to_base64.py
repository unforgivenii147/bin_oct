#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import sys
from pathlib import Path


def font_to_base64(font_path):
    font_data = font_path.read_bytes()
    return base64.b64encode(font_data).decode("utf-8")


def main():
    fname = Path(sys.argv[1].strip())
    b64_str = font_to_base64(fname)
    b64_path = fname.with_suffix(".txt")
    if b64_path.exists():
        print(f"{b64_path.name} exists. remove and run again")
        sys.exit(0)
    b64_path.write_text(b64_str, encoding="utf-8")
    print(f"{b64_path.name} created.")


if __name__ == "__main__":
    raise SystemExit(main())
