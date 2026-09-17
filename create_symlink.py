#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from pathlib import Path

BASHBIN: Path = Path.home() / "bashbin"
BIN: Path = Path.home() / "bin"


def process_dir(cwd: Path, ext: str) -> None:
    for path in cwd.glob(f"*.{ext}"):
        path = path.resolve()
        symlink_path = path.with_name(path.stem)
        if symlink_path.exists() and not symlink_path.is_symlink():
            symlink_path.unlink()
            symlink_path.symlink_to(path)
            print(f"Created: {symlink_path.name} -> {path.name}")
            continue
        if symlink_path.exists() and symlink_path.is_symlink():
            continue
        if not symlink_path.exists() or not symlink_path.is_symlink():
            symlink_path.symlink_to(path)
            print(f"Created: {symlink_path.name} -> {path.name}")


if __name__ == "__main__":
    process_dir(BASHBIN, "sh")
    process_dir(BIN, "py")
