#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from dh import MIME2EXT

DATA_URI_PATTERN = re.compile(
    r"data:(?P<mime>[^;,]*)(?P<params>(?:;[^;,]+=[^;,]+)*?);base64,\s*(?P<data>[A-Za-z0-9+/=]+)"
)


def get_extension(mime: str) -> str:
    if mime:
        if mime in MIME2EXT:
            return MIME2EXT.get(mime)[0]
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext
        parts = mime.split("/")
        if len(parts) == 2 and parts[1]:
            return f".{parts[1]}"
    return ".bin"


def process_file(path: Path, assets_dir: Path, processed: dict) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"⚠ Skipping {path}: {e}")
        return
    rel_to_assets = Path(assets_dir, path.parent)

    def replace_match(match: re.Match) -> str:
        full = match.group(0)
        mime = match.group("mime") or None
        data_b64 = match.group("data")
        hash_digest = hashlib.sha256(full.encode()).hexdigest()
        if hash_digest not in processed:
            ext = get_extension(mime)
            filename = f"{hash_digest}{ext}"
            asset_path = assets_dir / filename
            try:
                binary = base64.b64decode(data_b64)
            except Exception as e:
                print(f"⚠ Base64 decode error in {path}: {e}  – keeping original.")
                return full
            if not asset_path.exists():
                asset_path.write_bytes(binary)
                print(f"✔ Saved asset: {asset_path}")
            processed[hash_digest] = filename
        else:
            filename = processed[hash_digest]
        link = rel_to_assets / filename
        return link.as_posix()

    new_content = DATA_URI_PATTERN.sub(replace_match, content)
    if new_content != content:
        path.write_text(new_content, encoding="utf-8")
        print(f"✎ Updated {path}")


def main() -> None:
    mimetypes.init()
    assets_dir = Path("assets")
    assets_dir.mkdir(parents=True, exist_ok=True)
    processed = {}
    cwd = Path(".")
    for path in cwd.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".css", ".js", ".html"):
            process_file(path, assets_dir, processed)
    print("Done.")


if __name__ == "__main__":
    raise SystemExit(main())
