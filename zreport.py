#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import bz2
import gzip
import lzma
import sys
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Final

from dh import fsz

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)


def _try_import(module_name: str):
    try:
        import importlib

        return importlib.import_module(module_name)
    except ImportError:
        return None


zstd = _try_import("zstandard")
lz4f = _try_import("lz4.frame")
brotli = _try_import("brotli")
py7zr = _try_import("py7zr")


def _stream_size(readable, chunk=1 << 20) -> int:
    total = 0
    while True:
        data = readable.read(chunk)
        if not data:
            break
        total += len(data)
    return total


def _tar_size(fileobj, mode="r:*") -> int | None:
    try:
        with tarfile.open(fileobj=fileobj, mode=mode) as tf:
            return sum(m.size for m in tf.getmembers() if m.isfile())
    except Exception:
        return None


def get_zst_size(path: Path) -> tuple[int | None, str | None]:
    if not zstd:
        return (None, "zstandard not installed")
    try:
        with path.open("rb") as f:
            dctx = zstd.ZstdDecompressor()
            params = dctx.frame_parameters(f.read(32))
            if params.uncompressed_size:
                return (params.uncompressed_size, None)
            f.seek(0)
            return (_stream_size(dctx.stream_reader(f)), None)
    except Exception as e:
        return (None, str(e))


def get_xz_size(path: Path) -> tuple[int | None, str | None]:
    try:
        with lzma.open(path, "rb") as f:
            return (_stream_size(f), None)
    except Exception as e:
        return (None, str(e))


def get_gz_size(path: Path) -> tuple[int | None, str | None]:
    try:
        with gzip.open(path, "rb") as f:
            return (_stream_size(f), None)
    except Exception as e:
        return (None, str(e))


def get_bz2_size(path: Path) -> tuple[int | None, str | None]:
    try:
        with bz2.open(path, "rb") as f:
            return (_stream_size(f), None)
    except Exception as e:
        return (None, str(e))


def get_7z_size(path: Path) -> tuple[int | None, str | None]:
    if not py7zr:
        return (None, "py7zr not installed")
    try:
        with py7zr.SevenZipFile(path, mode="r") as z:
            return (
                sum(f.uncompressed for f in z.list() if f.uncompressed is not None),
                None,
            )
    except Exception as e:
        return (None, str(e))


def get_zip_size(path: Path) -> tuple[int | None, str | None]:
    try:
        with zipfile.ZipFile(path, "r") as z:
            return (sum(i.file_size for i in z.infolist()), None)
    except Exception as e:
        return (None, str(e))


HANDLERS: Final[dict[str, tuple[str, Callable]]] = {
    ".zst": ("zstd", get_zst_size),
    ".xz": ("xz", get_xz_size),
    ".gz": ("gzip", get_gz_size),
    ".bz2": ("bzip2", get_bz2_size),
    ".7z": ("7zip", get_7z_size),
    ".zip": ("zip", get_zip_size),
    ".whl": ("wheel", get_zip_size),
    ".tar": ("tar", lambda p: (_tar_size(p.open("rb"), "r:"), None)),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report uncompressed sizes of compressed files"
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    root = args.path.resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory")
        sys.exit(1)
    print(f"Scanning {root}...\n")
    grand_comp = grand_uncomp = total_files = 0
    col_fmt = "{:<30} {:<10} {:>15} {:>15} {:>8}"
    print(col_fmt.format("File", "Format", "Compressed", "Uncompressed", "Ratio"))
    print("-" * 40)
    for item in sorted(root.rglob("*")):
        if not item.is_file() or any(part in SKIP_DIRS for part in item.parts):
            continue
        handler_info = next(
            (v for k, v in HANDLERS.items() if item.name.endswith(k)), None
        )
        if not handler_info:
            continue
        label, handler = handler_info
        comp_size = item.stat().st_size
        uncomp_size, _err = handler(item)
        total_files += 1
        grand_comp += comp_size
        if uncomp_size is not None:
            grand_uncomp += uncomp_size
            ratio = uncomp_size / comp_size if comp_size > 0 else 0
            ratio_str = f"{ratio:.2f}x"
        else:
            ratio_str = "Error"
        name_trunc = item.name[:27] + "..." if len(item.name) > 30 else item.name
        print(
            col_fmt.format(
                name_trunc,
                label,
                fsz(comp_size),
                fsz(uncomp_size) if uncomp_size else "Error",
                ratio_str,
            )
        )
    print("-" * 40)
    print(f"Total files: {total_files}")
    print(f"Total compressed:   {fsz(grand_comp)}")
    print(f"Total uncompressed: {fsz(grand_uncomp)}")
    _, _, free = shutil.disk_usage(root)
    print(f"Free disk space:    {fsz(free)}")
    if grand_uncomp > free:
        print(
            f"\n⚠️  WARNING: Not enough space to extract all files! (Shortfall: {fsz(grand_uncomp - free)})"
        )


if __name__ == "__main__":
    import shutil

    raise SystemExit(main())
