#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import sys
from pathlib import Path

from dh import MIME2EXT

DATA_URL_RE = re.compile(
    r"url\(\s*(['\"]?)data:(?P<mime>[^;]+)(?:;charset=[^;]+)?;base64,(?P<data>[A-Za-z0-9+/=\s]+)\1\s*\)",
    re.IGNORECASE,
)
MIME_FALLBACKS = MIME2EXT


def ext_from_mime(mime: str) -> str:
    ext = mimetypes.guess_extension(mime)
    if ext:
        return ext
    return MIME_FALLBACKS.get(mime, ".bin")


def extract_css_base64(css_path: Path, out_dir: Path) -> int:
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    out_dir.mkdir(exist_ok=True)
    seen = {}

    def replace(match) -> str:
        mime = match.group("mime")
        raw = match.group("data").replace("\n", "").strip()
        binary = base64.b64decode(raw)
        sha = hashlib.sha256(binary).hexdigest()[:12]
        if sha not in seen:
            ext = ext_from_mime(mime)
            fname = f"asset-{sha}{ext}"
            (out_dir / fname).write_bytes(binary)
            seen[sha] = fname
        return f"url('{out_dir.name}/{seen[sha]}')"

    new_css = DATA_URL_RE.sub(replace, css)
    if new_css != css:
        css_path.write_text(new_css, encoding="utf-8")
    return len(seen)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: extract_css_base64.py file1.css [file2.css ...]")
        sys.exit(1)
    out_dir = Path("_static")
    total = 0
    for css_file in map(Path, sys.argv[1:]):
        if not css_file.exists():
            print(f"skip: {css_file}")
            continue
        count = extract_css_base64(css_file, out_dir)
        total += count
        print(f"{css_file}: extracted {count} assets")
    print(f"\nTotal saved assets: {total}")
    print(f"Output directory: ./{out_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
