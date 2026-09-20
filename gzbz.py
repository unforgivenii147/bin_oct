#!/data/data/com.termux/files/home/.local/bin/python
"""
compress_tool.py — unified multi-algorithm compression / decompression CLI.

Merges three previously independent scripts:

    * bzr.py    — bzip2 compression / decompression with tar support
    * gzr.py    — gzip  compression / decompression with tar support
    * gziper.py — recursive gzip file compression with a summary table

Original-script → merged-CLI mapping
------------------------------------
    bzr.py      →  python compress_tool.py bz2         [paths...]   # compress
                   python compress_tool.py bz2  -d     [paths...]   # decompress

    gzr.py      →  python compress_tool.py gz          [paths...]   # compress
                   python compress_tool.py gz   -d     [paths...]   # decompress

    gziper.py   →  python compress_tool.py gzip-files  [dirs...]    # compress only

Usage examples
--------------
    # Same as running `bzr.py` (no args): compress everything in the cwd
    python compress_tool.py bz2

    # Decompress every *.bz2 / *.tar.bz2 in the cwd
    python compress_tool.py bz2 -d

    # Same as running `gzr.py` on the current directory
    python compress_tool.py gz

    # Same as running `gziper.py` on two dirs with extra exclusions
    python compress_tool.py gzip-files ./src ./docs -e .pdf .jpg

Dependencies
------------
    loguru  (third-party; the original scripts already required it)
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import mmap
import shutil
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional, Sequence

from loguru import logger


# --------------------------------------------------------------------------- #
# Constants / defaults — everything that used to be hard-coded is exposed here
# (and can be overridden on the command line).
# --------------------------------------------------------------------------- #
DEFAULT_WORKERS: int = 8
DEFAULT_CHUNK_SIZE: int = 524_288  # 512 KiB — used by bzr.py / gzr.py
DEFAULT_GZIPER_CHUNK: int = 262_144  # 256 KiB — used by gziper.py
DEFAULT_MEM_THRESHOLD: int = 32_768  # 32 KiB  — in-memory vs. chunked cut-off
DEFAULT_MIN_FILE_SIZE: int = 1_024  # 1 KiB   — ignore tiny files
DEFAULT_BZ2_LEVEL: int = 9
DEFAULT_GZ_LEVEL: int = 9
DEFAULT_GZIPER_LEVEL: int = 9

# The three originals used slightly different "already compressed" sets.
# We preserve each one exactly so behaviour is identical.
EXCLUDE_BZ2: frozenset[str] = frozenset(
    {".bz2", ".xz", ".gz", ".br", ".zst", ".7z", ".zip", ".rar"}
)
EXCLUDE_GZ: frozenset[str] = frozenset(
    {".gz", ".bz2", ".xz", ".br", ".zst", ".7z", ".zip", ".rar"}
)
EXCLUDE_GZIPER: frozenset[str] = frozenset(
    {".gz", ".zip", ".bz2", ".xz", ".7z", ".rar", ".tar"}
)


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def human_size(n: float) -> str:
    """Return a human-readable size string, e.g. ``'1.5 MB'`` or ``'512 B'``."""
    units = ("B", "KB", "MB", "GB", "TB")
    v = float(n)
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{int(v)} B" if u == "B" else f"{v:.1f} {u}"
        v /= 1024.0
    return f"{v:.1f} TB"


def human_time(seconds: int) -> str:
    """Return ``HH:MM:SS`` for the given number of seconds."""
    return str(timedelta(seconds=seconds))


# --------------------------------------------------------------------------- #
# Byte-level compression primitives (algorithm dispatch)
# --------------------------------------------------------------------------- #
def compress_bytes(data: bytes, algo: str, level: int) -> bytes:
    """Compress *data* with the selected algorithm."""
    if algo == "bz2":
        return bz2.compress(data, compresslevel=level)
    if algo == "gz":
        return gzip.compress(data, compresslevel=level)
    raise ValueError(f"unknown algorithm: {algo!r}")


def decompress_bytes(data: bytes, algo: str) -> bytes:
    """Decompress *data* with the selected algorithm."""
    if algo == "bz2":
        return bz2.decompress(data)
    if algo == "gz":
        return gzip.decompress(data)
    raise ValueError(f"unknown algorithm: {algo!r}")


# --------------------------------------------------------------------------- #
# ProcessPool worker functions (must live at module level to be picklable)
# --------------------------------------------------------------------------- #
def _worker_compress_chunk(args: tuple[int, bytes, str, int]) -> tuple[int, bytes]:
    """Compress a single chunk; returns ``(index, compressed_bytes)``.

    Concatenated bz2/gz streams are valid inputs for the matching
    ``decompress_bytes`` function, so chunk boundaries are transparent.
    """
    idx, data, algo, level = args
    return idx, compress_bytes(data, algo, level)


def _worker_gzip_file(args: tuple[str, int, int]) -> tuple[str, bool, int, int, str]:
    """ProcessPool worker used by ``gzip-files`` mode (from gziper.py).

    Streams the file through ``gzip.open`` (rather than loading it into
    memory), which mirrors the original behaviour and keeps memory flat
    for very large inputs.
    """
    path_str, chunk_size, level = args
    src = Path(path_str)
    dst = Path(str(src) + ".gz")
    try:
        size = src.stat().st_size
        with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=level) as fo:
            shutil.copyfileobj(fi, fo, chunk_size)
        csize = dst.stat().st_size
        src.unlink()
        return (path_str, True, size, csize, "")
    except Exception as exc:  # noqa: BLE001
        if dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        return (path_str, False, 0, 0, str(exc))


# --------------------------------------------------------------------------- #
# Configuration container
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    """Runtime configuration shared by the ``bz2`` and ``gz`` subcommands."""

    algo: str  # 'bz2' or 'gz'
    level: int
    workers: int = DEFAULT_WORKERS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    mem_threshold: int = DEFAULT_MEM_THRESHOLD
    min_file_size: int = DEFAULT_MIN_FILE_SIZE

    @property
    def file_ext(self) -> str:
        return ".bz2" if self.algo == "bz2" else ".gz"

    @property
    def tar_ext(self) -> str:
        return ".tar.bz2" if self.algo == "bz2" else ".tar.gz"

    @property
    def exclude_ext(self) -> frozenset[str]:
        return EXCLUDE_BZ2 if self.algo == "bz2" else EXCLUDE_GZ


# --------------------------------------------------------------------------- #
# The main engine
# --------------------------------------------------------------------------- #
class Tool:
    """Compression / decompression engine for a single algorithm."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pool: Optional[ProcessPoolExecutor] = None

    # ----- pool lifecycle ------------------------------------------------- #
    def _get_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.cfg.workers)
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    def __enter__(self) -> "Tool":
        return self

    def __exit__(self, *exc_info) -> None:  # noqa: D401
        self.close()

    # ----- low-level file compression ------------------------------------- #
    def _compress_small(self, src: Path, dst: Path) -> bool:
        """Load the whole file into memory and compress it in one shot."""
        try:
            data = src.read_bytes()
            if not data:
                return False
            dst.write_bytes(compress_bytes(data, self.cfg.algo, self.cfg.level))
            return True
        except (OSError, MemoryError) as exc:
            logger.error(f"Memory compression failed for {src.name}: {exc}")
            return False

    def _compress_chunked(self, src: Path, dst: Path, size: int) -> bool:
        """Split the file into chunks, compress them in parallel, concatenate."""
        chunk = self.cfg.chunk_size
        try:
            n = (size + chunk - 1) // chunk
            with (
                dst.open("wb", buffering=1 << 20) as out,
                src.open("rb") as fh,
                mmap.mmap(fh.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
            ):
                # Slice the mmap — bytes are copied lazily and picklable.
                slices = [
                    (i, mm[i * chunk : min((i + 1) * chunk, size)]) for i in range(n)
                ]
            pool = self._get_pool()
            futures = [
                pool.submit(
                    _worker_compress_chunk, (idx, data, self.cfg.algo, self.cfg.level)
                )
                for idx, data in slices
            ]
            outputs: list[Optional[bytes]] = [None] * n
            for fut in futures:
                try:
                    idx, blob = fut.result()
                    outputs[idx] = blob
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Chunk compression failed: {exc}")
                    return False
            with dst.open("wb", buffering=1 << 20) as out:
                for blob in outputs:
                    if blob is None:
                        return False
                    out.write(blob)
            return True
        except (OSError, MemoryError) as exc:
            logger.error(f"Chunked compression failed for {src.name}: {exc}")
            return False

    def _compress_file(self, src: Path, dst: Path, size: int) -> bool:
        """Pick RAM vs. chunked path based on the memory threshold."""
        if size < self.cfg.mem_threshold:
            return self._compress_small(src, dst)
        return self._compress_chunked(src, dst, size)

    # ----- tar helpers ---------------------------------------------------- #
    @staticmethod
    def _create_tar(src_dir: Path, tar_path: Path) -> bool:
        """Create ``tar_path`` containing ``src_dir`` under its own name."""
        try:
            with tarfile.open(tar_path, "w") as tf:
                for p in src_dir.rglob("*"):
                    if p.is_file():
                        arcname = p.relative_to(src_dir.parent)
                        tf.add(p, arcname=str(arcname))
            return True
        except (OSError, tarfile.TarError) as exc:
            logger.error(f"  Failed to create tar archive: {exc}")
            return False

    @staticmethod
    def _extract_tar(tar_path: Path, dest: Path) -> bool:
        """Extract ``tar_path`` into the directory ``dest``."""
        try:
            dest.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tar_path, "r") as tf:
                tf.extractall(dest)
            return True
        except (OSError, tarfile.TarError) as exc:
            logger.error(f"  Failed to extract tar archive: {exc}")
            return False

    # ----- top-level directory compression -------------------------------- #
    def compress_dir(self, src_dir: Path) -> bool:
        """Compress ``src_dir`` to ``<name>.tar.<ext>``; delete on success."""
        tar_path = src_dir.with_name(src_dir.name + ".tar")
        out_path = src_dir.with_name(src_dir.name + self.cfg.tar_ext)
        try:
            print("  Creating tar archive...")
            if not self._create_tar(src_dir, tar_path) or not tar_path.exists():
                logger.error("  Failed to create tar archive")
                return False

            print(
                f"  Compressing tar archive with {self.cfg.algo} "
                f"(level {self.cfg.level})..."
            )
            size = tar_path.stat().st_size
            if not self._compress_file(tar_path, out_path, size):
                return False

            if not out_path.exists():
                return False
            csize = out_path.stat().st_size
            if csize == 0:
                logger.warning(f"Compressed archive empty for {src_dir.name}")
                out_path.unlink()
                return False
            if csize < size:
                tar_path.unlink()
                saved_pct = (size - csize) / size * 100
                print(
                    f"  ✓ Compressed archive: {saved_pct:.1f}% saved "
                    f"({human_size(size)} → {human_size(csize)})"
                )
                shutil.rmtree(src_dir)
                return True
            print("  ✗ Archive compression didn't save space, keeping .tar")
            out_path.unlink()
            return False
        except (OSError, MemoryError, tarfile.TarError) as exc:
            logger.error(f"  ✗ Failed to compress tar archive: {exc}")
            if tar_path.exists():
                tar_path.unlink()
            if out_path.exists():
                out_path.unlink()
            return False

    # ----- single-file compression ---------------------------------------- #
    def compress_single_file(self, src: Path) -> tuple[bool, int, int]:
        """Compress one file to ``<name><file_ext>``.

        Returns ``(ok, original_size, compressed_size)``.
        """
        dst = Path(str(src) + self.cfg.file_ext)
        if dst.exists():
            print(f"Skipping {src.name} - output already exists")
            return (False, 0, 0)
        try:
            size = src.stat().st_size
            if not size:
                return (False, 0, 0)
            if not self._compress_file(src, dst, size) or not dst.exists():
                return (False, 0, 0)
            csize = dst.stat().st_size
            if csize == 0:
                logger.warning(f"Compressed file empty for {src.name}")
                dst.unlink()
                return (False, 0, 0)
            if csize < size:
                src.unlink()
                saved_pct = (size - csize) / size * 100
                print(
                    f"  ✓ {src.name}: {saved_pct:.1f}% saved "
                    f"({human_size(size)} → {human_size(csize)})"
                )
                return (True, size, csize)
            print(f"  ✗ {src.name}: No space saved, removing compressed file")
            dst.unlink()
            return (False, 0, 0)
        except (OSError, PermissionError, MemoryError) as exc:
            logger.error(f"  ✗ Failed to compress {src.name}: {exc}")
            return (False, 0, 0)

    # ----- single-file decompression -------------------------------------- #
    def decompress_single_file(self, src: Path) -> bool:
        """Decompress ``<name><file_ext>`` back to ``<name>``."""
        if src.suffix != self.cfg.file_ext:
            return False
        dst = src.with_suffix("")
        try:
            data = src.read_bytes()
            if not data:
                return False
            dst.write_bytes(decompress_bytes(data, self.cfg.algo))
            print(
                f"  ✓ Decompressed {src.name}: "
                f"{human_size(src.stat().st_size)} → "
                f"{human_size(dst.stat().st_size)}"
            )
            src.unlink()
            return True
        except (OSError, EOFError, ValueError) as exc:
            logger.error(f"  ✗ Failed to decompress {src.name}: {exc}")
            return False

    # ----- archive decompression ------------------------------------------ #
    def decompress_archive(self, archive: Path) -> bool:
        """Decompress ``foo.tar.bz2`` / ``foo.tar.gz`` and extract ``foo/``."""
        tar_path = archive.with_suffix("")  # strip .bz2 / .gz → foo.tar
        # Destination: recreate the source directory in the parent of the archive.
        # (The original scripts used an off-by-one path here; this is the
        # intended behaviour and matches what the tar was created from.)
        dest = archive.parent
        try:
            print(f"\n  Decompressing {archive.name}...")
            data = archive.read_bytes()
            tar_path.write_bytes(decompress_bytes(data, self.cfg.algo))
            print(f"    Extracting tar to {dest}/...")
            if self._extract_tar(tar_path, dest):
                tar_path.unlink()
                archive.unlink()
                print(f"  ✓ Extracted {archive.name} to {dest}/")
                return True
            logger.error(f"  ✗ Failed to extract {archive.name}")
            return False
        except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
            logger.error(f"  ✗ Failed to decompress {archive.name}: {exc}")
            if tar_path.exists():
                tar_path.unlink()
            return False

    # ----- collection helpers --------------------------------------------- #
    def collect_dirs(self, root: Path) -> list[Path]:
        return [p for p in root.glob("*") if p.is_dir() and not p.is_symlink()]

    def collect_files(self, root: Path) -> list[Path]:
        """Top-level files in *root* that aren't already compressed."""
        out: list[Path] = []
        for p in root.glob("*"):
            if not p.is_file() or p.is_symlink():
                continue
            if p.suffix in self.cfg.exclude_ext:
                continue
            try:
                if p.stat().st_size >= self.cfg.min_file_size:
                    out.append(p)
            except (OSError, PermissionError):
                pass
        return out

    def collect_archives(self, root: Path) -> list[Path]:
        return [
            p
            for p in root.glob(f"*{self.cfg.tar_ext}")
            if p.is_file() and not p.is_symlink()
        ]

    def collect_compressed(self, root: Path) -> list[Path]:
        ext = self.cfg.file_ext
        return [
            p
            for p in root.glob(f"*{ext}")
            if p.is_file()
            and not p.is_symlink()
            and not p.name.endswith(self.cfg.tar_ext)
        ]

    # ----- high-level compress -------------------------------------------- #
    def compress(self, paths: Sequence[Path]) -> None:
        cwd = Path.cwd()

        if paths:
            dirs = [p for p in paths if p.is_dir()]
            files = [p for p in paths if p.is_file()]
        else:
            dirs = self.collect_dirs(cwd)
            files = self.collect_files(cwd)

        # --- directories → tar.<ext> ------------------------------------ #
        if dirs:
            print(f"\n📁 Compressing {len(dirs)} directories...")
            for d in sorted(dirs):
                try:
                    rel = d.relative_to(cwd)
                except ValueError:
                    rel = d
                print(f"\n  Processing {rel}...")
                if self.compress_dir(d):
                    print(
                        f"  ✓ Successfully compressed {rel} "
                        f"to {d.name}{self.cfg.tar_ext}"
                    )
                else:
                    logger.error(f"  ✗ Failed to compress {rel}")

        # --- files → <name>.<ext> -------------------------------------- #
        if not files:
            print("\n📄 No files to compress")
            return

        print(
            f"\n📄 Compressing {len(files)} files with "
            f"{self.cfg.algo} max compression..."
        )
        orig = comp = ok = 0
        for i, f in enumerate(sorted(files), 1):
            print(f"\n[{i}/{len(files)}] {f.name}")
            success, o, c = self.compress_single_file(f)
            if success:
                ok += 1
                orig += o
                comp += c

        if ok > 0:
            saved = orig - comp
            pct = saved / orig * 100 if orig else 0.0
            print(f"\n{'=' * 40}")
            print(f"✅ Compressed {ok}/{len(files)} files")
            print(f"📊 Original size: {human_size(orig)}")
            print(f"📦 Compressed size: {human_size(comp)}")
            print(f"💾 Space saved: {human_size(saved)} ({pct:.1f}%)")
            print(f"{'=' * 40}")
        elif files:
            logger.error("\n❌ No files were successfully compressed")

    # ----- high-level decompress ------------------------------------------ #
    def decompress(self, paths: Sequence[Path]) -> None:
        cwd = Path.cwd()

        # --- tar archives ------------------------------------------------- #
        if paths:
            archives = [
                p for p in paths if p.is_file() and p.name.endswith(self.cfg.tar_ext)
            ]
        else:
            archives = self.collect_archives(cwd)

        if archives:
            print(f"\n📦 Decompressing {len(archives)} archives...")
            for a in sorted(archives):
                self.decompress_archive(a)

        # --- single compressed files ------------------------------------- #
        if paths:
            singles = [
                p
                for p in paths
                if p.is_file()
                and p.suffix == self.cfg.file_ext
                and not p.name.endswith(self.cfg.tar_ext)
            ]
        else:
            singles = self.collect_compressed(cwd)

        if not singles:
            print(f"\n📄 No {self.cfg.file_ext} files to decompress")
            return

        print(f"\n📄 Decompressing {len(singles)} {self.cfg.algo} files...")
        total_in = total_out = ok = 0
        for i, f in enumerate(sorted(singles), 1):
            print(f"\n[{i}/{len(singles)}] {f.name}")
            try:
                total_in += f.stat().st_size
            except OSError:
                pass
            if self.decompress_single_file(f):
                ok += 1
                dst = f.with_suffix("")
                if dst.exists():
                    total_out += dst.stat().st_size

        if ok > 0:
            print(f"\n{'=' * 40}")
            print(f"✅ Decompressed {ok}/{len(singles)} files")
            print(f"📦 Compressed size: {human_size(total_in)}")
            print(f"📊 Decompressed size: {human_size(total_out)}")
            print(f"{'=' * 40}")
        elif singles:
            logger.error("\n❌ No files were successfully decompressed")


# --------------------------------------------------------------------------- #
# gzip-files mode (behaviour of the original gziper.py)
# --------------------------------------------------------------------------- #
def run_gzip_files(
    directories: Sequence[Path],
    excludes: Sequence[str],
    workers: int,
    chunk_size: int,
    level: int,
) -> int:
    """Recursively gzip every non-excluded file below *directories*."""
    exclude_set: set[str] = set(EXCLUDE_GZIPER)
    for e in excludes:
        if not e.startswith("."):
            e = "." + e
        exclude_set.add(e)

    resolved_dirs = [d.resolve() for d in directories]

    print("=" * 40)
    print("🔍 GZIP Compression Tool (Maximum Compression - Level 9)".center(70))
    print("-" * 40)
    print("📂 Processing directories:")
    for d in resolved_dirs:
        print("   •", d)
    print("🚫 Excluding extensions:", ",".join(sorted(exclude_set)))

    # ----- collect --------------------------------------------------------- #
    files: list[Path] = []
    for d in resolved_dirs:
        if not d.exists():
            logger.warning(f"Directory '{d}' does not exist, skipping...")
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix not in exclude_set:
                files.append(p)

    if not files:
        logger.success("✅ No files found to compress!")
        return 0

    print("📊 Found", len(files), "file(s) to compress")
    print("-" * 40)
    print(
        f"{'File':<50} {'Original':>10} {'Compressed':>10} {'Ratio':>8} {'Status':>10}"
    )
    print("-" * 40)

    # ----- compress -------------------------------------------------------- #
    total_files = ok = fail = 0
    total_orig = total_comp = 0
    start = time.time()
    cwd = Path.cwd()

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_worker_gzip_file, (str(f), chunk_size, level)) for f in files
        ]
        for fut in futures:
            path_str, success, o, c, err = fut.result()
            total_files += 1
            try:
                rel = str(Path(path_str).relative_to(cwd))
            except ValueError:
                rel = path_str
            display = ("..." + rel[-44:]) if len(rel) > 47 else rel

            if success:
                ok += 1
                total_orig += o
                total_comp += c
                ratio = f"{(1 - c / o) * 100:.1f}%" if o else "N/A"
                print(
                    f"{display:<50} {human_size(o):>10} "
                    f"{human_size(c):>10} {ratio:>8} {'✅':>10}"
                )
            else:
                fail += 1
                print(f"{display:<50} {'N/A':>10} {'N/A':>10} {'N/A':>8} {'❌':>10}")
                if err:
                    logger.warning(f"   ⚠ Error: {err}")

    elapsed = time.time() - start

    # ----- summary -------------------------------------------------------- #
    print("=" * 40)
    print("📊 COMPRESSION SUMMARY".center(70))
    print("-" * 40)
    print(f"  Total files processed: {total_files}")
    print(f"  Successfully compressed: {ok} ✅")
    print(f"  Failed compressions: {fail} ❌")
    print(f"  Original total size: {human_size(total_orig)}")
    print(f"  Compressed total size: {human_size(total_comp)}")
    if total_orig > 0:
        ratio = (1 - total_comp / total_orig) * 100
        saved = total_orig - total_comp
        print(f"  Overall compression ratio: {ratio:.1f}%")
        print(f"  Space saved: {human_size(saved)}")
    print(f"  Time elapsed: {human_time(int(elapsed))}")
    print("-" * 40)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _add_pool_options(
    sp: argparse.ArgumentParser, algo_default_level: int, chunk_default: int
) -> None:
    """Add the flags shared by the ``bz2`` and ``gz`` subcommands."""
    sp.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress instead of compress"
    )
    sp.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Explicitly select compression (default)",
    )
    sp.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current working directory)",
    )
    sp.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel worker processes (default: {DEFAULT_WORKERS})",
    )
    sp.add_argument(
        "-l",
        "--level",
        type=int,
        default=algo_default_level,
        help=f"Compression level (default: {algo_default_level})",
    )
    sp.add_argument(
        "--chunk-size",
        type=int,
        default=chunk_default,
        help=f"Chunk size for parallel compression in bytes (default: {chunk_default})",
    )
    sp.add_argument(
        "--mem-threshold",
        type=int,
        default=DEFAULT_MEM_THRESHOLD,
        help=f"Files smaller than this are compressed in memory "
        f"(default: {DEFAULT_MEM_THRESHOLD})",
    )
    sp.add_argument(
        "--min-file-size",
        type=int,
        default=DEFAULT_MIN_FILE_SIZE,
        help=f"Ignore files smaller than this many bytes "
        f"(default: {DEFAULT_MIN_FILE_SIZE})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compress_tool",
        description="Unified bz2/gz compression & decompression tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Mapping from the original scripts:\n"
            "  bzr.py     -> compress_tool.py bz2         [paths...]\n"
            "  bzr.py -d  -> compress_tool.py bz2 -d      [paths...]\n"
            "  gzr.py     -> compress_tool.py gz          [paths...]\n"
            "  gzr.py -d  -> compress_tool.py gz  -d      [paths...]\n"
            "  gziper.py  -> compress_tool.py gzip-files  [dirs...]\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=False)

    # --- bz2 subcommand -------------------------------------------------- #
    bz2_p = sub.add_parser("bz2", help="bzip2 compression / decompression (bzr.py)")
    _add_pool_options(bz2_p, DEFAULT_BZ2_LEVEL, DEFAULT_CHUNK_SIZE)

    # --- gz subcommand --------------------------------------------------- #
    gz_p = sub.add_parser(
        "gz", help="gzip compression / decompression with tar support (gzr.py)"
    )
    _add_pool_options(gz_p, DEFAULT_GZ_LEVEL, DEFAULT_CHUNK_SIZE)

    # --- gzip-files subcommand ------------------------------------------- #
    gf_p = sub.add_parser("gzip-files", help="recursive gzip on files only (gziper.py)")
    gf_p.add_argument(
        "directories",
        nargs="*",
        type=Path,
        help="Directories to walk recursively (default: '.')",
    )
    gf_p.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[],
        help="Additional file extensions to exclude (e.g. .pdf .jpg)",
    )
    gf_p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel worker processes (default: {DEFAULT_WORKERS})",
    )
    gf_p.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_GZIPER_CHUNK,
        help=f"Streaming copy buffer size in bytes (default: {DEFAULT_GZIPER_CHUNK})",
    )
    gf_p.add_argument(
        "-l",
        "--level",
        type=int,
        default=DEFAULT_GZIPER_LEVEL,
        help=f"gzip compression level (default: {DEFAULT_GZIPER_LEVEL})",
    )

    return parser


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "gzip-files":
            return run_gzip_files(
                directories=args.directories or [Path(".")],
                excludes=args.exclude,
                workers=args.workers,
                chunk_size=args.chunk_size,
                level=args.level,
            )

        # -- bz2 / gz -------------------------------------------------- #
        algo = "bz2" if args.command == "bz2" else "gz"
        cfg = Config(
            algo=algo,
            level=args.level,
            workers=args.workers,
            chunk_size=args.chunk_size,
            mem_threshold=args.mem_threshold,
            min_file_size=args.min_file_size,
        )
        paths = [p.resolve() for p in (args.paths or [])]

        with Tool(cfg) as tool:
            if args.decompress:
                tool.decompress(paths)
            else:
                tool.compress(paths)
        return 0
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.error(f"\n❌ Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
