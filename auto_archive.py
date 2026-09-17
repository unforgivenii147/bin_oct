#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import bz2
import gzip
import logging
import lzma
import multiprocessing as mp
import sys
import tempfile
import traceback
from io import BytesIO
from pathlib import Path

from dh import fsz

try:
    import zstandard as zstd
except ImportError:
    zstd = None
try:
    import brotli
except ImportError:
    brotli = None
try:
    import lz4.frame as lz4frame
except ImportError:
    lz4frame = None
try:
    import py7zr
except ImportError:
    py7zr = None
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)


def read_file(path: Path) -> bytes:
    return path.read_bytes()


def compress_zstd(data: bytes, level: int) -> bytes:
    if zstd is None:
        raise RuntimeError("zstandard not installed")
        level = min(level, 21)
    cctx = zstd.ZstdCompressor(level=level)
    buf = BytesIO()
    with cctx.stream_writer(buf, closefd=False) as writer:
        writer.write(data)
    return buf.getvalue()


def compress_brotli(data: bytes, level: int) -> bytes:
    if brotli is None:
        raise RuntimeError("brotli not installed")
    return brotli.compress(data, quality=level)


def compress_lz4(data: bytes, level: int) -> bytes:
    if lz4frame is None:
        raise RuntimeError("lz4 not installed")
    return lz4frame.compress(data, compression_level=level)


def compress_gz(data: bytes, level: int) -> bytes:
    buf = BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=level) as f:
        f.write(data)
    return buf.getvalue()


def compress_bz2(data: bytes, level: int) -> bytes:
    return bz2.compress(data, compresslevel=level)


def compress_xz(data: bytes, level: int) -> bytes:
    return lzma.compress(data, format=lzma.FORMAT_XZ, preset=level)


def compress_7z(data: bytes, level: int, src_name: str) -> bytes:
    if py7zr is None:
        raise RuntimeError("py7zr not installed")
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        src = td_path / src_name
        src.write_bytes(data)
        archive = td_path / "out.7z"
        filters = [{"id": py7zr.FILTER_LZMA2, "preset": level}]
        with py7zr.SevenZipFile(archive, "w", filters=filters) as sz:
            sz.write(src, src_name)
        return archive.read_bytes()


def _make_algorithms():
    algos = []
    if zstd:
        algos.append(("zstd", ".zst", compress_zstd, 1, 21))
    else:
        log.warning("zstandard not available — skipping")
    if brotli:
        algos.append(("brotli", ".br", compress_brotli, 1, 11))
    else:
        log.warning("brotli not available — skipping")
    algos.append(("gz", ".gz", compress_gz, 1, 9))
    algos.append(("bz2", ".bz2", compress_bz2, 1, 9))
    algos.append(("xz", ".xz", compress_xz, 1, 9))
    if lz4frame:
        algos.append(("lz4", ".lz4", compress_lz4, 1, 9))
    else:
        log.warning("lz4 not available — skipping")
    if py7zr:
        algos.append(("7z", ".7z", None, 1, 9))
    else:
        log.warning("py7zr not available — skipping")
    return algos


ALGORITHMS = _make_algorithms()


def best_for_algo(
    data: bytes, name: str, ext: str, fn, min_l: int, max_l: int, src_name: str = "data"
) -> tuple[str, str, int, bytes] | None:
    best_size = None
    best_level = min_l
    best_compressed = None
    for level in range(min_l, max_l + 1):
        try:
            if name == "7z":
                compressed = compress_7z(data, level, src_name)
            else:
                compressed = fn(data, level)
            size = len(compressed)
            if best_size is None or size < best_size:
                best_size = size
                best_level = level
                best_compressed = compressed
        except Exception as exc:
            log.error("Error compressing with %s level=%d: %s", name, level, exc)
            log.debug(traceback.format_exc())
    if best_compressed is None:
        return None
    return name, ext, best_level, best_compressed


def process_file(src: Path, out_dir: Path | None = None) -> Path | None:
    log.info("Processing: %s (%s)", src, fsz(src.stat().st_size))
    try:
        data = read_file(src)
    except Exception as exc:
        log.error("Cannot read %s: %s", src, exc)
        return None
    original_size = len(data)
    results: list[tuple[str, str, int, bytes]] = []
    for name, ext, fn, min_l, max_l in ALGORITHMS:
        result = best_for_algo(data, name, ext, fn, min_l, max_l, src_name=src.name)
        if result:
            r_name, _r_ext, r_level, r_bytes = result
            log.info(
                "  %-8s best level=%2d  %s → %s  (%.1f%%)",
                r_name,
                r_level,
                fsz(original_size),
                fsz(len(r_bytes)),
                100 * len(r_bytes) / original_size,
            )
            results.append(result)
    if not results:
        log.error("All algorithms failed for %s", src)
        return None
    winner = min(results, key=lambda r: len(r[3]))
    w_name, w_ext, w_level, w_bytes = winner
    dest_dir = out_dir if out_dir else src.parent
    dest = dest_dir / (src.name + w_ext)
    try:
        dest.write_bytes(w_bytes)
    except Exception as exc:
        log.error("Cannot write %s: %s", dest, exc)
        return None
    log.info(
        "  Winner → %s (algo=%s level=%d size=%s)",
        dest.name,
        w_name,
        w_level,
        fsz(len(w_bytes)),
    )
    return dest


def _worker(args) -> Path | None:
    src, out_dir = args
    try:
        return process_file(src, out_dir)
    except Exception as exc:
        log.error("Worker error on %s: %s", src, exc)
        return None


SKIP_EXTENSIONS = {
    ".zst",
    ".br",
    ".gz",
    ".bz2",
    ".xz",
    ".lz4",
    ".7z",
    ".zip",
    ".rar",
    ".zstd",
    ".lzma",
}


def collect_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() not in SKIP_EXTENSIONS
    ]


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not target.exists():
        log.error("Path does not exist: %s", target)
        sys.exit(1)
    if target.is_file():
        result = process_file(target)
        if result is None:
            sys.exit(1)
    elif target.is_dir():
        files = collect_files(target)
        if not files:
            log.info("No compressible files found in %s", target)
            sys.exit(0)
        log.info("Found %d file(s) in %s", len(files), target)
        cpu_count = mp.cpu_count() or 1
        workers = min(cpu_count, len(files))
        log.info("Using %d worker(s)", workers)
        args = [(f, None) for f in files]
        with mp.Pool(processes=workers) as pool:
            results = pool.map(_worker, args)
        success = sum(1 for r in results if r is not None)
        log.info("Done. %d/%d file(s) compressed successfully.", success, len(files))
    else:
        log.error("Target is neither a file nor a directory: %s", target)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
