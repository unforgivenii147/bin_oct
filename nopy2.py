#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

TARGET_FILES = {"WHEEL"}
PREFIX = "Tag: py2-none-any"


def clean_text(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith(PREFIX)
    ) + ("\n" if text.endswith("\n") else "")


def clean_file(path: str) -> None:
    try:
        original = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    cleaned = clean_text(original)
    if cleaned != original:
        Path(path).write_text(cleaned, encoding="utf-8")


def process_zip(path: str) -> None:
    tmp = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            base = Path(item.filename).name
            if base in TARGET_FILES:
                try:
                    text = data.decode("utf-8", errors="ignore")
                    cleaned = clean_text(text)
                    data = cleaned.encode("utf-8")
                except Exception:
                    pass
            zout.writestr(item, data)
    shutil.move(tmp, path)


def process_tar(path: str) -> None:
    tmp_dir = tempfile.mkdtemp()
    tmp_tar = tempfile.mktemp(suffix=".tar.gz")
    with tarfile.open(path, "r:*") as tar:
        tar.extractall(tmp_dir)
    for root, _, files in os.walk(tmp_dir):
        for name in files:
            if name in TARGET_FILES:
                clean_file(os.path.join(root, name))
    with tarfile.open(tmp_tar, "w:gz") as tar:
        tar.add(tmp_dir, arcname="")
    shutil.move(tmp_tar, path)
    shutil.rmtree(tmp_dir)


def dispatch_archive(path: str) -> None:
    name = path.lower()
    if name.endswith((".zip", ".whl")):
        process_zip(path)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        process_tar(path)


def main() -> None:
    for root, _, files in os.walk("."):
        for name in files:
            full_path = os.path.join(root, name)
            if name in TARGET_FILES:
                clean_file(full_path)
                continue
            if name.lower().endswith((".zip", ".whl", ".tar.gz", ".tgz", ".tar")):
                dispatch_archive(full_path)


if __name__ == "__main__":
    raise SystemExit(main())
