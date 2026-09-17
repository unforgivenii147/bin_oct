#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
from pathlib import Path

import magic

MIME_TO_EXT = {
    "text/html": "html",
    "application/json": "json",
    "application/javascript": "js",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/zip": "zip",
    "application/gzip": "gz",
    "application/x-tar": "tar",
    "text/xml": "xml",
}


def detect_text_based_extension(text: str):
    text = text.strip()
    if text.startswith("#!") and "python" in text:
        return "py"
    if any(k in text for k in ["def ", "class ", "import ", "from ", "__main__"]):
        return "py"
    if text.startswith("#!") and ("sh" in text or "bash" in text):
        return "sh"
    if text.startswith(("# ", "## ")) or "---" in text:
        return "md"
    if text.startswith("---") or (": " in text and "\n" in text):
        return "yaml"
    if "=" in text and "[" in text and "]" in text:
        return "toml"
    if text.startswith("[") and "]" in text:
        return "ini"
    if any(
        text.lower().startswith(cmd)
        for cmd in ["select ", "insert ", "update ", "delete ", "create "]
    ):
        return "sql"
    if "{" in text and "}" in text and ":" in text:
        return "css"
    if "," in text and "\n" in text:
        return "csv"
    if text.startswith("<?xml"):
        return "xml"
    return None


def detect_extension(path: str, mime_type: str):
    if mime_type in MIME_TO_EXT:
        return MIME_TO_EXT[mime_type]
    if mime_type == "text/plain":
        try:
            with Path(path).open(encoding="utf-8", errors="ignore") as f:
                sample = f.read(4096)
            guessed = detect_text_based_extension(sample)
            if guessed:
                return guessed
        except:
            pass
    return None


def safe_rename(src: str, dst: str) -> Path:
    dst = Path(dst)
    src = Path(src)
    if not dst.exists():
        src.rename(dst)
        return dst
    base, ext = dst.stem, dst.suffix
    counter = 1
    new_path = Path(f"{base} ({counter}){ext}")
    while new_path.exists():
        counter += 1
        new_path = Path(f"{base} ({counter}){ext}")
    src.rename(new_path)
    return new_path


def correct_file_extension(root: str = ".") -> None:
    mime = magic.Magic(mime=True)
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if Path(path).is_symlink():
                continue
            try:
                mime_type = mime.from_file(path)
            except:
                print(f"Skipping unreadable: {path}")
                continue
            new_ext = detect_extension(path, mime_type)
            if not new_ext:
                continue
            parts = name.rsplit(".", 1)
            current_ext = parts[1].lower() if len(parts) == 2 else ""
            if current_ext == new_ext:
                continue
            base = parts[0] if len(parts) == 2 else name
            new_name = f"{base}.{new_ext}"
            new_path = os.path.join(dirpath, new_name)
            print(f"Renaming: {name}  →  {new_name}")
            final_path = safe_rename(path, new_path)
            if final_path != new_path:
                print(f" ⚠  Collision detected. Saved as: {Path(final_path).name}")


if __name__ == "__main__":
    correct_file_extension()
