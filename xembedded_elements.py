#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from dh import MIME2EXT, get_nobinary

OUTPUT_DIR = Path("extracted_base64")
DATA_URL_RE = re.compile(
    "data:(?P<mime>[-\\w.+/]+);base64,(?P<data>[A-Za-z0-9+/=\\s]+)", re.IGNORECASE
)


def infer_extension(mime: str) -> str:
    return MIME2EXT.get(mime.lower(), mime.rsplit("/", maxsplit=1)[-1])[0]


def decode_base64(data: str) -> bytes:
    cleaned = "".join(data.split())
    return base64.b64decode(cleaned, validate=False)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:15]


def extract_from_html(html: str) -> Iterable[tuple[str, bytes]]:
    for matchz in DATA_URL_RE.finditer(html):
        mime = matchz.group("mime")
        raw_data = matchz.group("data")
        try:
            decoded = decode_base64(raw_data)
        except Exception:
            continue
        yield (mime, decoded)


def save_asset(mime: str, data: bytes) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ext = infer_extension(mime)
    digest = content_hash(data)
    filename = f"{digest}.{ext}"
    path = OUTPUT_DIR / filename
    if not path.exists():
        path.write_bytes(data)
    return path


def main() -> None:
    cwd = Path.cwd()
    seen_hashes = set()
    extracted_count = 0
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_nobinary(cwd)
    for html_file in files:
        try:
            html = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for mime, data in extract_from_html(html):
            digest = content_hash(data)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            save_asset(mime, data)
            extracted_count += 1
    print(f"{extracted_count} elements extracted.")


if __name__ == "__main__":
    raise SystemExit(main())
