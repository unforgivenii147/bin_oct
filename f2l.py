#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    fn = sys.argv[1]
    path = Path(fn)
    with path.open(encoding="utf-8") as f:
        lines = [line.strip() for line in f]
    items = []
    for line in lines:
        quote_char = "'" if '"' in line else '"'
        items.append(f"{quote_char}{line}{quote_char}")
    formatted_content = "{" + ", ".join(items) + "}"
    path.write_text(formatted_content, encoding="utf-8")
    try:
        subprocess.run(
            ["termux-clipboard-set"],
            input=formatted_content,
            text=True,
            capture_output=True,
        )
        print(f"✓ Updated and copied: {path}")
    except FileNotFoundError:
        print(f"✓ File updated: {path}")
        print("⚠ Install termux-api for clipboard support")


if __name__ == "__main__":
    raise SystemExit(main())
