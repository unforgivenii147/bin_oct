#!/data/data/com.termux/files/home/.local/bin/python
"""
Convert *.tar.<codec> archive files recursively under the current directory
into another compression codec (*.tar.gz, *.tar.bz2, *.tar.xz, *.tar.zst,
*.tar.lz4, *.tar.br, *.tar.7z) using a multiprocessing pool of 8 workers,
logging with loguru, and printing total disk usage before and after.
"""

from __future__ import annotations

import bz2
import contextlib
import gzip
import lzma
import os
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Final

import brotli
import lz4.frame
import py7zr
import zstandard as zstd
from dh import fsz, gsz
from loguru import logger

CHUNK: Final[int] = 1024 * 1024
XZ_PRESET_9: Final[int] = 9
POOL_SIZE: Final[int] = 8

ALLOWED_CODECS: Final[frozenset[str]] = frozenset(
    {"gz", "zst", "xz", "bz2", "lz4", "br", "7z"}
)


def parse_tar_codec(p: Path) -> tuple[str, str] | None:
    """Parse ``*.tar.<codec>`` path into ``(stem, codec)`` or ``None``."""
    parts = p.name.split(".")
    if len(parts) < 3 or parts[-2] != "tar":
        return None
    codec = parts[-1].lower()
    stem = ".".join(parts[:-2])
    if not stem:
        stem = "archive"
    return (stem, codec)


def dst_path_for(src_path: Path, dst_codec: str) -> Path:
    """Return the destination path for ``src_path`` converted to ``dst_codec``."""
    parse = parse_tar_codec(src_path)
    stem = parse[0] if parse else src_path.stem
    return src_path.with_name(f"{stem}.tar.{dst_codec}")


def write_tar_bytes_with_decoder_to_file(src: Path, dst: Path, codec: str) -> None:
    """Decompress ``src`` (as ``codec``) and write raw tar bytes to ``dst``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if codec == "gz":
        with gzip.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    elif codec == "bz2":
        with bz2.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    elif codec == "xz":
        with (
            lzma.open(src, "rb", format=lzma.FORMAT_XZ) as f_in,
            dst.open("wb") as f_out,
        ):
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    elif codec == "zst":
        dctx = zstd.ZstdDecompressor()
        with (
            src.open("rb") as f_in,
            dctx.stream_reader(f_in) as zreader,
            dst.open("wb") as f_out,
        ):
            while True:
                chunk = zreader.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    elif codec == "br":
        dec = brotli.Decompressor()
        with src.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                data = f_in.read(CHUNK)
                if not data:
                    break
                out = dec.process(data)
                if out:
                    f_out.write(out)
            tail = dec.finish()
            if tail:
                f_out.write(tail)
    elif codec == "lz4":
        with lz4.frame.open(src, "rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    else:
        raise ValueError(f"Unsupported src codec: {codec}")


def write_compressed_tar_bytes_from_tar(src_tar: Path, dst: Path, codec: str) -> None:
    """Compress ``src_tar`` (raw tar) with ``codec`` and write to ``dst``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if codec == "gz":
        with src_tar.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=9) as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                f_out.write(chunk)
    elif codec == "bz2":
        comp = bz2.BZ2Compressor(compresslevel=9)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = comp.compress(chunk)
                if out:
                    f_out.write(out)
            tail = comp.flush()
            if tail:
                f_out.write(tail)
    elif codec == "xz":
        comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=-1, preset=XZ_PRESET_9)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = comp.compress(chunk)
                if out:
                    f_out.write(out)
            tail = comp.flush()
            if tail:
                f_out.write(tail)
    elif codec == "zst":
        cctx = zstd.ZstdCompressor(level=22)
        with (
            src_tar.open("rb") as f_in,
            dst.open("wb") as f_out,
            cctx.stream_writer(f_out) as zw,
        ):
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                zw.write(chunk)
    elif codec == "br":
        compressor = brotli.Compressor(quality=11)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = compressor.process(chunk)
                if out:
                    f_out.write(out)
            tail = compressor.finish()
            if tail:
                f_out.write(tail)
    elif codec == "lz4":
        comp = lz4.frame.LZ4FrameCompressor(block_size=lz4.frame.BLOCKSIZE_MAX)
        with src_tar.open("rb") as f_in, dst.open("wb") as f_out:
            while True:
                chunk = f_in.read(CHUNK)
                if not chunk:
                    break
                out = comp.compress(chunk)
                if out:
                    f_out.write(out)
            tail = comp.flush()
            if tail:
                f_out.write(tail)
    elif codec == "7z":
        raise RuntimeError("Use py7zr path for dst codec 7z")
    else:
        raise ValueError(f"Unsupported dst codec: {codec}")


def safe_unlink(p: Path) -> None:
    """Delete ``p`` if it exists, ignoring any error."""
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass


def _extract_tar_from_7z(src: Path, tmp_tar: Path) -> None:
    """Extract the first (tar) member of a ``.tar.7z`` archive to ``tmp_tar``."""
    tmpdir = Path(tempfile.mkdtemp(prefix="tar7z_dec_"))
    try:
        with py7zr.SevenZipFile(src, mode="r") as z:
            z.extractall(path=tmpdir)
        extracted: Path | None = next(tmpdir.glob("*.tar"), None)
        if extracted is None:
            files: list[Path] = [p for p in tmpdir.rglob("*") if p.is_file()]
            if not files:
                raise RuntimeError("No files extracted from .tar.7z")
            extracted = files[0]
        extracted.replace(tmp_tar)
    finally:
        for p in tmpdir.rglob("*"):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
        with contextlib.suppress(Exception):
            tmpdir.rmdir()


def convert_one(src_str: str, dst_codec: str) -> tuple[str, bool, str]:
    """Convert a single ``*.tar.<src_codec>`` file to ``dst_codec``."""
    src = Path(src_str)
    parse = parse_tar_codec(src)
    if not parse:
        return (src.name, False, "Not a *.tar.<codec> file")
    stem, src_codec = parse
    if src_codec == dst_codec:
        return (src.name, True, "Skipped (already target codec)")
    dst = dst_path_for(src, dst_codec)
    if dst.exists():
        return (src.name, True, f"Skipped (exists): {dst.name}")
    tmp_tar = src.with_name(f".__tmp_tar_conv_{os.getpid()}_{stem}.tar")
    try:
        if src_codec == "7z":
            _extract_tar_from_7z(src, tmp_tar)
        else:
            write_tar_bytes_with_decoder_to_file(src, tmp_tar, src_codec)
        if dst_codec == "7z":
            with py7zr.SevenZipFile(dst, mode="w") as z:
                z.write(tmp_tar, arcname=tmp_tar.name)
        else:
            write_compressed_tar_bytes_from_tar(tmp_tar, dst, dst_codec)
        src.unlink()
        return (src.name, True, f"converted -> {dst.name} (removed original)")
    except Exception as e:
        safe_unlink(dst)
        return (src.name, False, f"error: {e}")
    finally:
        safe_unlink(tmp_tar)


def find_tar_inputs(cwd: Path) -> list[Path]:
    """Find all supported ``*.tar.<codec>`` files recursively under ``cwd``."""
    tar_inputs: list[Path] = []
    for p in cwd.rglob("*.tar.*"):
        if not p.is_file():
            continue
        parsed = parse_tar_codec(p)
        if not parsed:
            continue
        _, codec = parsed
        if codec in ALLOWED_CODECS:
            tar_inputs.append(p)
    return sorted(tar_inputs)


def main() -> None:
    """CLI entry point: parse args, run conversions, print disk usage report."""
    if len(sys.argv) < 2:
        logger.error("Usage: python3 convert.py <target_codec>   (example: xz)")
        sys.exit(1)
    dst_codec = sys.argv[1].strip().lower()
    if dst_codec not in ALLOWED_CODECS:
        logger.error(
            f"Unsupported target codec: {dst_codec}. Allowed: {sorted(ALLOWED_CODECS)}"
        )
        sys.exit(1)

    cwd = Path.cwd()
    tar_inputs = find_tar_inputs(cwd)
    if not tar_inputs:
        print("No *.tar.<codec> files found recursively in current directory.")
        return

    initial_bytes = gsz(cwd)
    results: list[tuple[str, bool, str]] = []

    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(convert_one, (str(p), dst_codec)) for p in tar_inputs
        ]
        for ar in async_results:
            try:
                results.append(ar.get())
            except Exception as e:
                results.append(("<unknown>", False, f"error: {e}"))

    final_bytes = gsz(cwd)
    delta = final_bytes - initial_bytes
    ok_count = sum(1 for _, ok, _ in results if ok)
    fail_count = len(results) - ok_count

    print(
        f"Converted inputs: {len(tar_inputs)}; OK: {ok_count}; Failed/Skipped: {fail_count}"
    )
    for name, ok, msg in sorted(results, key=lambda x: x[0]):
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}: {msg}")

    print(f"Disk usage (sum of file sizes under cwd) initial: {fsz(initial_bytes)}")
    print(f"Disk usage (sum of file sizes under cwd) final:   {fsz(final_bytes)}")
    if delta < 0:
        print(f"Saved: {fsz(-delta)}")
    elif delta > 0:
        print(f"Extra used: {fsz(delta)}")
    else:
        print("No disk usage change (by summed file sizes).")


if __name__ == "__main__":
    raise SystemExit(main())
