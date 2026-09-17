#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

from dh import get_files, mpf3, unique_path


def process_file(path: str | Path) -> None:
    path = Path(path)
    new_name = ""
    if path.name.endswith(".txz"):
        new_name = path.name.replace(".txz", ".whl")
    elif path.name.endswith(".tar.xz"):
        new_name = path.name.replace(".tar.xz", ".whl")
    else:
        return
    target = path.with_name(new_name)
    if target.exists():
        print(f"[SKIP] {target.name} already exists")
        target = unique_path(target)
    try:
        with (
            tarfile.open(path, "r:xz") as tf,
            zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf,
        ):
            for member in tf.getmembers():
                if member.isdir():
                    continue
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                zf.writestr(member.name, extracted.read())
        print(f"[OK] {target.name}")
    except Exception as e:
        print(f"[ERROR] {path.name}: {e}")


def main() -> None:
    args = sys.argv[1:]
    cwd = Path().cwd()
    files = (
        [Path(arg) for arg in args] if args else get_files(cwd, ext=[".tar.xz", ".txz"])
    )
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
