#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

BASE64_IMG_REGEX = re.compile(
    r"data:image/(?P<ext>[a-zA-Z0-9+]+);base64,(?P<data>[A-Za-z0-9+/=\n\r]+)"
)


def extract_images_from_file(path: Path, output_dir: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    matches = BASE64_IMG_REGEX.finditer(text)
    count = 0
    for m in matches:
        ext = m.group("ext").lower()
        b64_data = m.group("data").replace("\n", "").replace("\r", "")
        try:
            img_bytes = base64.b64decode(b64_data, validate=False)
        except Exception:
            continue
        digest = hashlib.sha1(img_bytes).hexdigest()[:12]
        filename = f"{path.stem}_{digest}.{ext}"
        output_path = output_dir / filename
        output_path.write_bytes(img_bytes)
        count += 1
    return count


def scan_and_extract(base_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    target_exts = {".ipynb", ".js", ".html"}
    total_found = 0
    print(f"\n🔍 Scanning: {base_dir.resolve()}\n")
    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in target_exts:
            continue
        found = extract_images_from_file(path, output_dir)
        total_found += found
        if found:
            print(f"📸 Extracted {found} images from {path}")
    print(f"\n✅ Extraction complete. Total images saved: {total_found}")


if __name__ == "__main__":
    base_dir = Path.cwd()
    output_dir = Path("extracted_images")
    scan_and_extract(base_dir, output_dir)
