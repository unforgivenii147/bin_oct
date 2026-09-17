#!/data/data/com.termux/files/home/.local/bin/python
"""
Generate a Python CLI script that converts archives between tar-based
compression formats and zip-based container formats.

The generated script should:
- Accept one or more input archive paths (files or directories) as
  positional arguments; when none are given, scan the current working
  directory.
- Accept a required `-t/--to` flag selecting the target format from
  .tar.gz, .tar.xz, .tar.lz4, .tar.7z, .tar.br, .tar.zst, .tar.bz2,
  .tar.sz, .zip, and .whl.
- Auto-detect each input's container/compression from its extension
  (the tar family plus .zip/.whl), parse it into a stream of
  (name, bytes) entries, and repack those entries into the requested
  output format:
    * tar family: build a tar stream with tarfile and wrap it with the
      appropriate outer compression (gzip/bz2/xz/zstd/lz4/brotli/snappy/
      7z, or none for plain .tar).
    * zip/whl:   write a zipfile with deflate compression.
- Write the new archive next to the source and delete the source on
  success, skipping when the destination already exists or equals the
  source, and cleaning up partial outputs on failure.
- Convert files concurrently with multiprocessing.Pool.imap_unordered
  using a fixed pool of 8 workers (no CLI flag controls parallelism).
- Log progress, per-file results, and a net byte-delta summary using
  loguru; use pathlib for all filesystem access; and include complete
  type hints plus docstrings on every function.
"""

from __future__ import annotations

import argparse
import bz2
import contextlib
import gzip
import io
import lzma
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import (
    BinaryIO,
    Final,
    List,
    Optional,
    Tuple,
)

import brotli
import cramjam
import lz4.frame
import py7zr
import zstandard as zstd
from loguru import logger

POOL_SIZE: Final[int] = 8

TAR_FAMILY: Final[frozenset[str]] = frozenset(
    {
        ".tar",
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar.br",
        ".tar.lz4",
        ".tar.7z",
        ".tar.sz",
    }
)
ZIP_FAMILY: Final[frozenset[str]] = frozenset({".zip", ".whl"})

# All known extensions, longest-first for unambiguous suffix matching.
INPUT_EXTS: Final[tuple[str, ...]] = tuple(
    sorted(TAR_FAMILY | ZIP_FAMILY, key=len, reverse=True)
)

# Extensions the user may select via -t/--to.
ALLOWED_TO_FORMATS: Final[frozenset[str]] = frozenset(
    {
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar.br",
        ".tar.lz4",
        ".tar.7z",
        ".tar.sz",
        ".zip",
        ".whl",
    }
)

Entry = tuple[str, bytes]
ConvertArgs = tuple[str, str]  # (src_path, target_ext)
ConvertResult = tuple[str, int, bool, str]  # (src, delta, ok, message)


def detect_ext(path: Path) -> str | None:
    """Return the canonical extension that ``path`` matches, if any.

    Args:
        path: Candidate archive path.

    Returns:
        The matched extension from ``INPUT_EXTS``, or ``None`` if the file
        extension is not a recognized archive format.
    """
    name: str = path.name.lower()
    suffix: str
    for suffix in INPUT_EXTS:
        if name.endswith(suffix):
            return suffix
    return None


@contextlib.contextmanager
def _open_tar_input(path: Path, ext: str) -> Iterator[BinaryIO]:
    """Open ``path`` as a decompressed binary stream for tar parsing.

    Args:
        path: Source archive path.
        ext: Canonical input extension (one of ``TAR_FAMILY``).

    Yields:
        A binary file-like object positioned at the start of the inner tar
        stream.

    Raises:
        ValueError: If ``ext`` is not a known tar-family extension.
    """
    if ext == ".tar":
        with path.open("rb") as f:
            yield f
    elif ext == ".tar.gz":
        with gzip.open(path, "rb") as f:
            yield f
    elif ext == ".tar.bz2":
        with bz2.open(path, "rb") as f:
            yield f
    elif ext == ".tar.xz":
        with lzma.open(path, "rb") as f:
            yield f
    elif ext == ".tar.zst":
        with path.open("rb") as f_raw:
            dctx: zstd.ZstdDecompressor = zstd.ZstdDecompressor()
            with dctx.stream_reader(f_raw) as reader:
                yield reader  # type: ignore[misc]
    elif ext == ".tar.lz4":
        with lz4.frame.open(path, "rb") as f:
            yield f
    elif ext == ".tar.br":
        data: bytes = brotli.decompress(path.read_bytes())
        yield io.BytesIO(data)
    elif ext == ".tar.sz":
        data = bytes(cramjam.snappy.decompress(path.read_bytes()))
        yield io.BytesIO(data)
    elif ext == ".tar.7z":
        with py7zr.SevenZipFile(str(path), mode="r") as archive:
            members = archive.readall()
            for bio in members.values():
                yield io.BytesIO(bio.read())
                return
        raise ValueError(f"empty 7z archive: {path}")
    else:
        raise ValueError(f"unsupported tar input extension: {ext}")


def iter_entries(path: Path, ext: str) -> Iterator[Entry]:
    """Yield ``(name, bytes)`` entries from the archive at ``path``.

    Args:
        path: Source archive path.
        ext: Canonical input extension as returned by ``detect_ext``.

    Yields:
        Each contained file as a ``(name, data)`` pair. Directory entries
        are skipped.

    Raises:
        ValueError: If ``ext`` is not a supported archive format.
    """
    if ext in ZIP_FAMILY:
        with zipfile.ZipFile(path, "r") as zf:
            info: zipfile.ZipInfo
            for info in zf.infolist():
                if info.is_dir():
                    continue
                with zf.open(info) as f:
                    yield info.filename, f.read()
        return

    if ext in TAR_FAMILY:
        with (
            _open_tar_input(path, ext) as stream,
            tarfile.open(fileobj=stream, mode="r|") as tf,
        ):
            member: tarfile.TarInfo
            for member in tf:
                if not member.isfile():
                    continue
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                yield member.name, fobj.read()
        return

    raise ValueError(f"unsupported input extension: {ext}")


def _add_tar_entries(tf: tarfile.TarFile, entries: Iterable[Entry]) -> int:
    """Append ``entries`` to the open tar file ``tf``.

    Args:
        tf: Open ``TarFile`` in stream-write mode.
        entries: Iterable of ``(name, data)`` pairs.

    Returns:
        The total number of uncompressed payload bytes written.
    """
    total: int = 0
    name: str
    data: bytes
    for name, data in entries:
        info: tarfile.TarInfo = tarfile.TarInfo(name=name)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        total += len(data)
    return total


def _write_tar(entries: Iterable[Entry], dst: Path, ext: str) -> int:
    """Write ``entries`` as a tar archive compressed per ``ext``.

    Args:
        entries: Iterable of ``(name, data)`` pairs.
        dst: Destination archive path.
        ext: Target extension (one of ``TAR_FAMILY`` minus ``.tar``).

    Returns:
        The total number of uncompressed payload bytes written.

    Raises:
        ValueError: If ``ext`` is not a supported tar-family target.
    """
    if ext == ".tar.gz":
        with gzip.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.bz2":
        with bz2.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.xz":
        with (
            lzma.open(dst, "wb", preset=9) as f,
            tarfile.open(fileobj=f, mode="w|") as tf,
        ):
            return _add_tar_entries(tf, entries)
    if ext == ".tar.zst":
        cctx: zstd.ZstdCompressor = zstd.ZstdCompressor(level=9)
        with dst.open("wb") as f_raw, cctx.stream_writer(f_raw) as writer:
            with tarfile.open(fileobj=writer, mode="w|") as tf:  # type: ignore[arg-type]
                return _add_tar_entries(tf, entries)
    if ext == ".tar.lz4":
        with lz4.frame.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.br":
        buf: io.BytesIO = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w|") as tf:
            total: int = _add_tar_entries(tf, entries)
        dst.write_bytes(brotli.compress(buf.getvalue(), quality=11))
        return total
    if ext == ".tar.sz":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w|") as tf:
            total = _add_tar_entries(tf, entries)
        dst.write_bytes(bytes(cramjam.snappy.compress(buf.getvalue())))
        return total
    if ext == ".tar.7z":
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            with tmp_path.open("wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
                total = _add_tar_entries(tf, entries)
            with py7zr.SevenZipFile(str(dst), mode="w") as archive:
                archive.write(str(tmp_path), arcname="archive.tar")
            return total
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    raise ValueError(f"unsupported tar output extension: {ext}")


def write_entries(entries: Iterable[Entry], dst: Path, ext: str) -> int:
    """Write ``entries`` as an archive at ``dst`` using format ``ext``.

    Args:
        entries: Iterable of ``(name, data)`` pairs.
        dst: Destination archive path.
        ext: Target extension (must be in ``ALLOWED_TO_FORMATS``).

    Returns:
        The total number of uncompressed payload bytes written.

    Raises:
        ValueError: If ``ext`` is not a supported output format.
    """
    if ext in ZIP_FAMILY:
        total: int = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            name: str
            data: bytes
            for name, data in entries:
                zf.writestr(name, data)
                total += len(data)
        return total
    if ext in TAR_FAMILY:
        return _write_tar(entries, dst, ext)
    raise ValueError(f"unsupported output extension: {ext}")


def convert_one(args: ConvertArgs) -> ConvertResult:
    """Convert a single archive to the requested target format.

    Args:
        args: Tuple of ``(src_path_str, target_ext)``.

    Returns:
        A tuple ``(src_path_str, delta_bytes, ok, message)`` where
        ``delta_bytes`` is ``dst_size - src_size`` on success.
    """
    src_str: str
    target_ext: str
    src_str, target_ext = args
    src: Path = Path(src_str)

    input_ext: str | None = detect_ext(src)
    if input_ext is None:
        return (src_str, 0, False, f"unsupported input format: {src.name}")

    # Derive the destination filename by stripping the matched suffix.
    stem: str = src.name
    suffix: str
    for suffix in INPUT_EXTS:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    dst: Path = src.with_name(stem + target_ext)

    if dst == src:
        return (src_str, 0, True, f"skipped (already {target_ext}): {src.name}")
    if dst.exists():
        return (src_str, 0, True, f"skipped (exists): {dst.name}")

    try:
        src_size: int = src.stat().st_size
        write_entries(iter_entries(src, input_ext), dst, target_ext)
        dst_size: int = dst.stat().st_size
        src.unlink()
        delta: int = dst_size - src_size
        return (
            src_str,
            delta,
            True,
            f"converted -> {dst.name}, removed original",
        )
    except Exception as exc:  # noqa: BLE001
        try:
            if dst.exists():
                dst.unlink()
        except Exception:  # noqa: BLE001
            pass
        return (src_str, 0, False, f"error: {exc}")


def _collect_inputs(args: list[str]) -> list[Path]:
    """Resolve CLI path arguments into a list of convertible archives.

    Args:
        args: Raw CLI path arguments; empty means scan the current
            directory (non-recursively).

    Returns:
        A list of supported archive file paths.
    """
    candidates: list[Path] = []
    if not args:
        candidates.extend(Path.cwd().iterdir())
    else:
        arg: str
        for arg in args:
            p: Path = Path(arg)
            if p.is_dir():
                candidates.extend(p.iterdir())
            else:
                candidates.append(p)

    files: list[Path] = []
    p: Path
    for p in candidates:
        if not p.is_file():
            continue
        if detect_ext(p) is None:
            logger.warning("Skipping unsupported file: {}", p.name)
            continue
        files.append(p)
    return files


def format_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Args:
        num_bytes: Number of bytes (may be negative).

    Returns:
        A string such as ``"1.23 MB"``.
    """
    value: float = float(num_bytes)
    unit: str
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        A configured ``argparse.ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        description=("Convert archives between tar-compressed and zip-based formats.")
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help=("Input archive files or directories (default: current directory)"),
    )
    parser.add_argument(
        "-t",
        "--to",
        required=True,
        choices=sorted(ALLOWED_TO_FORMATS),
        help="Target archive format (e.g. .tar.xz or .zip)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Entry point for the archive conversion CLI.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, 1 on invalid input).
    """
    parser: argparse.ArgumentParser = _build_parser()
    args: argparse.Namespace = parser.parse_args(
        list(argv) if argv is not None else None
    )

    target_ext: str = args.to
    files: list[Path] = _collect_inputs(list(args.inputs))
    if not files:
        logger.warning("No convertible archives found.")
        return 0

    logger.info("Found {} archive(s); converting to {}", len(files), target_ext)

    tasks: list[ConvertArgs] = [(str(p), target_ext) for p in files]
    results: list[ConvertResult] = []

    with Pool(processes=POOL_SIZE) as pool:
        result: ConvertResult
        for result in pool.imap_unordered(convert_one, tasks):
            results.append(result)

    ok_count: int = sum(1 for _, _, ok, _ in results if ok)
    fail_count: int = len(results) - ok_count
    net_delta: int = sum(delta for _, delta, _, _ in results)

    logger.info(
        "Summary: total={} ok={} failed/skipped={}",
        len(files),
        ok_count,
        fail_count,
    )

    src: str
    delta: int
    ok: bool
    msg: str
    for src, delta, ok, msg in sorted(results, key=lambda x: x[0]):
        status: str = "OK" if ok else "FAIL"
        logger.info("[{}] {}: {}", status, Path(src).name, msg)

    if net_delta < 0:
        logger.info("Net space saved: {}", format_size(-net_delta))
    elif net_delta > 0:
        logger.info("Net extra used: {}", format_size(net_delta))
    else:
        logger.info("Net disk usage change: none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
