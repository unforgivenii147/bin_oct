#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
from pathlib import Path


def main() -> None:
    cwd = Path.cwd()
    for font_path in cwd.glob("*.ttf"):
        output_filename = f"{font_path.stem}.txt"
        binary_data = font_path.read_bytes()
        b64_string = base64.b64encode(binary_data).decode("utf-8")
        Path(output_filename).write_text(b64_string, encoding="utf-8")
        print(f"Converted: {font_path.name} -> {output_filename}")


if __name__ == "__main__":
    raise SystemExit(main())
