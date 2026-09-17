#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

INPUT_FILE = Path("urls.txt")
OUTPUT_FILE = Path("filtered_urls.txt")
EXT_PATTERN = re.compile(r"\.(min\.)?(js|css)$", re.IGNORECASE)


def is_static_asset(url: str) -> bool:
    url = url.strip()
    if not url:
        return False
    parsed = urlparse(url)
    path = parsed.path
    return bool(EXT_PATTERN.search(path))


def main() -> None:
    if not INPUT_FILE.exists():
        print("urls.txt not found.")
        return
    seen = set()
    filtered = []
    with INPUT_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and is_static_asset(url) and url not in seen:
                seen.add(url)
                filtered.append(url)
    OUTPUT_FILE.write_text("\n".join(filtered), encoding="utf-8")
    print(f"Kept {len(filtered)} URLs.")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    raise SystemExit(main())
