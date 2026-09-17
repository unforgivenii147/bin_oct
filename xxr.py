#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import bz2
import gzip
import lzma
import os
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import brotlicffi as brotli
import py7zr
import zstandard as zstd
from dh import cprint, fsz, gsz, mpf3
from loguru import logger

SUPPORTED_EXTS = {
    ".tar",
    ".tar.xz",
    ".tar.gz",
    ".tar.br",
    ".tar.zst",
    ".tar.7z",
    ".tar.zip",
    ".xz",
    ".gz",
    ".br",
    ".zst",
    ".7z",
    ".zip",
    ".bz2",
    ".tar.bz2",
}
COMPRESS_MODE = "zstd"
CHUNK_SIZE = 1024 * 1024


@dataclass
class Result:
    ok: bool
    src: str
    dst: str | None = None
    error: str | None = None
    original_size: int = 0
    new_size: int = 0


def has_compressed_suffix(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in SUPPORTED_EXTS)


def output_name_for_file(path: Path, mode: str) -> Path:
    ext_map = {
        "xz": ".xz",
        "gz": ".gz",
        "brotli": ".br",
        "zstd": ".zst",
        "7z": ".7z",
        "zip": ".zip",
    }
    if mode not in ext_map:
        raise ValueError(f"Unsupported mode: {mode}")
    return path.with_name(path.name + ext_map[mode])


def output_name_for_dir(dir_path: Path, mode: str) -> Path:
    ext_map = {
        "xz": ".tar.xz",
        "gz": ".tar.gz",
        "brotli": ".tar.br",
        "zstd": ".tar.zst",
        "7z": ".tar.7z",
        "zip": ".tar.zip",
    }
    if mode not in ext_map:
        raise ValueError(f"Unsupported mode: {mode}")
    return dir_path.parent / f"{dir_path.name}{ext_map[mode]}"


def copy_chunks(src_fd, dst_fd, chunk_size: int = 32768) -> None:
    while chunk := src_fd.read(chunk_size):
        dst_fd.write(chunk)


def compress_streaming(
    src: Path, dst: Path, compress_func: Callable, is_dir: bool = False
) -> None:
    temp_path = dst.with_suffix(".tmp")
    try:
        if is_dir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tf:
                tar_temp = Path(tf.name)
                with tarfile.open(tar_temp, "w") as tar:
                    tar.add(src, arcname=src.name)
                compress_func(tar_temp, temp_path)
                tar_temp.unlink()
        else:
            compress_func(src, temp_path)
        os.replace(temp_path, dst)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise


def compress_file_xz(src: Path, dst: Path) -> None:
    with (
        src.open("rb") as fin,
        lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fout,
    ):
        copy_chunks(fin, fout)


def compress_file_gz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=9) as fout:
        copy_chunks(fin, fout)


def compress_file_bz2(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, bz2.open(dst, "wb", compresslevel=9) as fout:
        copy_chunks(fin, fout)


def compress_file_brotli(src: Path, dst: Path) -> None:
    if brotli is None:
        raise RuntimeError("brotlicffi is not installed")
    compressor = brotli.Compressor(quality=11)
    with src.open("rb") as fin, dst.open("wb") as fout:
        while chunk := fin.read(CHUNK_SIZE):
            compressed = compressor.process(chunk)
            if compressed:
                fout.write(compressed)
        fout.write(compressor.finish())


def compress_file_zstd(src: Path, dst: Path) -> None:
    if zstd is None:
        raise RuntimeError("zstandard is not installed")
    cctx = zstd.ZstdCompressor(level=22)
    with (
        src.open("rb") as fin,
        dst.open("wb") as fout,
        cctx.stream_writer(fout) as compressor,
    ):
        copy_chunks(fin, compressor)


def compress_file_zip(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(
        dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        zf.write(src, arcname=src.name)


def compress_file_7z(src: Path, dst: Path) -> None:
    if py7zr is None:
        raise RuntimeError("py7zr is not installed")
    with py7zr.SevenZipFile(
        dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": 9}]
    ) as zf:
        zf.write(src, arcname=src.name)


def compress_one(path_str: str, mode: str, is_dir: bool) -> Result:
    src = Path(path_str)
    original_size = gsz(src)
    result = Result(ok=False, src=str(src), original_size=original_size)
    compress_funcs = {
        "xz": compress_file_xz,
        "gz": compress_file_gz,
        "brotli": compress_file_brotli,
        "zstd": compress_file_zstd,
        "7z": compress_file_7z,
        "zip": compress_file_zip,
        "bz2": compress_file_bz2,
    }
    try:
        if mode not in compress_funcs:
            raise ValueError(f"Unsupported compression mode: {mode}")
        if is_dir:
            dst = output_name_for_dir(src, mode)
            compress_streaming(src, dst, compress_funcs[mode], is_dir=True)
            shutil.rmtree(src)
        else:
            dst = output_name_for_file(src, mode)
            compress_streaming(src, dst, compress_funcs[mode], is_dir=False)
            src.unlink()
        result.dst = str(dst)
        result.new_size = gsz(dst)
        result.ok = True
        return result
    except Exception as e:
        logger.exception(f"Failed to compress {src}")
        result.error = str(e)
        return result


def decompress_stream_tar(
    src: Path, decompress_func: Callable, dst_dir: Path, extension: str
) -> Path:
    extracted_path = dst_dir / src.name[: -len(extension)]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tf:
        tar_temp = Path(tf.name)
        with src.open("rb") as fin:
            decompress_func(fin, tf)
    try:
        with tarfile.open(tar_temp, "r:") as tar:
            tar.extractall(path=dst_dir, filter="data")
    finally:
        tar_temp.unlink()
    return extracted_path


def freader(p, func):
    with func.open(p, "rb") as f:
        return f.read()


def decompress_one(path_str: str) -> Result:
    src = Path(path_str)
    original_size = gsz(src)
    result = Result(ok=False, src=str(src), original_size=original_size)
    name = src.name.lower()
    dst_dir = src.parent
    try:
        if name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".tar.br", ".tar.zst")):

            def copy_via_lzma(fin, fout):
                with lzma.open(fin, "rb") as lzma_fin:
                    copy_chunks(lzma_fin, fout)

            def copy_via_gzip(fin, fout):
                with gzip.open(fin, "rb") as gz_fin:
                    copy_chunks(gz_fin, fout)

            def copy_via_bz2(fin, fout):
                with bz2.open(fin, "rb") as bz2_fin:
                    copy_chunks(bz2_fin, fout)

            def copy_via_brotli(fin, fout):
                decompressor = brotli.Decompressor()
                while chunk := fin.read(CHUNK_SIZE):
                    fout.write(decompressor.process(chunk))
                fout.write(decompressor.finish())

            def copy_via_zstd(fin, fout):
                dctx = zstd.ZstdDecompressor()
                with dctx.stream_reader(fin) as reader:
                    copy_chunks(reader, fout)

            ext_map = {
                ".tar.xz": (7, copy_via_lzma),
                ".tar.gz": (6, copy_via_gzip),
                ".tar.bz2": (7, copy_via_bz2),
                ".tar.br": (7, copy_via_brotli),
                ".tar.zst": (8, copy_via_zstd),
            }
            for ext, (_len_offset, decompress_func) in ext_map.items():
                if name.endswith(ext):
                    extracted = decompress_stream_tar(
                        src, decompress_func, dst_dir, ext
                    )
                    result.dst = str(extracted)
                    break
        elif name.endswith(".tar"):
            extracted = dst_dir / src.name[:-4]
            with tarfile.open(src, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            result.dst = str(extracted)
        elif name.endswith((".xz", ".gz", ".bz2", ".br", ".zst")):
            ext_map = {
                ".xz": (freader(src, lzma), src.with_suffix("")),
                ".gz": (freader(src, gzip), src.with_suffix("")),
                ".bz2": (freader(src, bz2), src.with_suffix("")),
                ".br": (decompress_brotli_file(src), src.with_suffix("")),
                ".zst": (decompress_zstd_file(src), src.with_suffix("")),
            }
            for ext, (decompressed_data, dst_path) in ext_map.items():
                if name.endswith(ext):
                    if isinstance(decompressed_data, Path):
                        pass
                    else:
                        with decompressed_data as fin, dst_path.open("wb") as fout:
                            copy_chunks(fin, fout)
                    result.dst = str(dst_path)
                    break
        elif name.endswith((".7z", ".zip")):
            ext_map = {
                ".7z": (py7zr.SevenZipFile(src, "r"), src.stem),
                ".zip": (zipfile.ZipFile(src, "r"), src.stem),
            }
            for ext, (archive, extract_name) in ext_map.items():
                if name.endswith(ext):
                    with archive as zf:
                        zf.extractall(path=dst_dir)
                    result.dst = str(dst_dir / extract_name)
                    break
        else:
            raise ValueError(f"Unsupported archive type: {src}")
        src.unlink()
        if result.dst:
            result.new_size = gsz(Path(result.dst))
        result.ok = True
        return result
    except Exception as e:
        logger.exception(f"Failed to decompress {src}")
        result.error = str(e)
        return result


def decompress_brotli_file(src: Path) -> Path:
    dst = src.with_suffix("")
    decompressor = brotli.Decompressor()
    with src.open("rb") as fin, dst.open("wb") as fout:
        while chunk := fin.read(CHUNK_SIZE):
            fout.write(decompressor.process(chunk))
        fout.write(decompressor.finish())
    return dst


def decompress_zstd_file(src: Path) -> Path:
    dst = src.with_suffix("")
    with src.open("rb") as fin, dst.open("wb") as fout:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(fin) as reader:
            copy_chunks(reader, fout)
    return dst


def collect_top_level_items(base: Path) -> list[tuple[Path, bool]]:
    items = []
    for p in base.iterdir():
        if p.is_symlink():
            continue
        if p.is_file() and (not has_compressed_suffix(p)):
            items.append((p, False))
        elif p.is_dir() and ".git" not in p.parts and (not has_compressed_suffix(p)):
            items.append((p, True))
    return items


def worker_func(item_tuple: tuple[Path, bool]) -> Result:
    path, is_dir = item_tuple
    return compress_one(str(path), COMPRESS_MODE, is_dir)


def main() -> None:
    global COMPRESS_MODE
    cwd = Path.cwd()
    before = gsz(cwd)
    parser = argparse.ArgumentParser(
        description="Compress/decompress current directory recursively."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", help="Compress")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress")
    parser.add_argument(
        "--threads", type=int, default=os.cpu_count(), help="Number of threads to use"
    )
    parser.add_argument(
        "-7", "--7z", dest="use_7z", action="store_true", help="Use py7zr"
    )
    parser.add_argument(
        "-z", "--zstd", action="store_true", help="Use zstandard (default)"
    )
    parser.add_argument("-x", "--xz", action="store_true", help="Use xz")
    parser.add_argument("-g", "--gz", action="store_true", help="Use gzip")
    parser.add_argument("-b", "--brotli", action="store_true", help="Use brotlicffi")
    parser.add_argument("--zip", action="store_true", help="Use zipfile")
    parser.add_argument("--bz2", action="store_true", help="Use bz2")
    args = parser.parse_args()
    if not args.compress and (not args.decompress):
        args.compress = True
        args.zstd = True
    if args.decompress:
        targets = [
            p for p in Path().iterdir() if p.is_file() and has_compressed_suffix(p)
        ]
        if not targets:
            print("No compressed files found to decompress.")
            return
        print(f"Found {len(targets)} compressed files. Starting decompression...")
        mpf3(decompress_one, [str(t) for t in targets], max_workers=args.threads)
    else:
        mode_map = {
            "use_7z": "7z",
            "zstd": "zstd",
            "gz": "gz",
            "brotli": "brotli",
            "zip": "zip",
            "xz": "xz",
            "bz2": "bz2",
        }
        mode = next(
            (mode_map[flag] for flag in mode_map if getattr(args, flag)), "zstd"
        )
        items_to_process = collect_top_level_items(cwd)
        if not items_to_process:
            print("No files or directories to compress.")
            return
        print(
            f"Found {len(items_to_process)} items to compress using mode '{mode}'. Starting compression..."
        )
        COMPRESS_MODE = mode
        mpf3(worker_func, items_to_process, max_workers=args.threads)
    after = gsz(cwd)
    space_freed = before - after
    if space_freed <= 0:
        print("No space freed or size increased")
        return
    ratio = space_freed / before * 40 if before > 0 else 0
    print("Space freed:", end=" ")
    cprint(f"{fsz(space_freed)} | {ratio:.1f}% reduction", "cyan")


if __name__ == "__main__":
    raise SystemExit(main())
